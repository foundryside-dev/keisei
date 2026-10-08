use numpy::{PyArray3, PyArrayMethods, ToPyArray};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use shogi_core::GameState;

use crate::action_mapper::{ACTION_SPACE_SIZE, ActionMapper, DefaultActionMapper};
use crate::katago_observation::KataGoObservationGenerator;
use crate::observation::{DefaultObservationGenerator, ObservationGenerator};
use crate::spatial_action_mapper::{SPATIAL_ACTION_SPACE_SIZE, SpatialActionMapper};
use crate::spectator_data::{build_spectator_dict, color_name, move_notation, move_usi};

// ---------------------------------------------------------------------------
// ActionMode dispatch (mirrors vec_env.rs)
// ---------------------------------------------------------------------------

enum SpectatorActionMode {
    Default(DefaultActionMapper),
    Spatial(SpatialActionMapper),
}

impl SpectatorActionMode {
    fn action_space_size(&self) -> usize {
        match self {
            SpectatorActionMode::Default(_) => ACTION_SPACE_SIZE,
            SpectatorActionMode::Spatial(_) => SPATIAL_ACTION_SPACE_SIZE,
        }
    }

    fn encode(
        &self,
        mv: shogi_core::Move,
        perspective: shogi_core::Color,
    ) -> Result<usize, String> {
        match self {
            SpectatorActionMode::Default(m) => {
                <DefaultActionMapper as ActionMapper>::encode(m, mv, perspective)
            }
            SpectatorActionMode::Spatial(m) => {
                <SpatialActionMapper as ActionMapper>::encode(m, mv, perspective)
            }
        }
    }

    fn decode(
        &self,
        idx: usize,
        perspective: shogi_core::Color,
    ) -> Result<shogi_core::Move, String> {
        match self {
            SpectatorActionMode::Default(m) => {
                <DefaultActionMapper as ActionMapper>::decode(m, idx, perspective)
            }
            SpectatorActionMode::Spatial(m) => {
                <SpatialActionMapper as ActionMapper>::decode(m, idx, perspective)
            }
        }
    }
}

// ---------------------------------------------------------------------------
// SpectatorEnv
// ---------------------------------------------------------------------------

/// Single-game environment for spectator/display use.
///
/// Key differences from VecEnv:
/// - Returns rich Python dicts (acceptable — not on the hot path)
/// - Does NOT auto-reset on game end — stays ended until explicitly `reset()`
/// - Provides `to_dict()` for JSON serialization (Streamlit dashboard)
/// - `legal_actions()` returns list of valid action indices
#[pyclass]
pub struct SpectatorEnv {
    game: GameState,
    max_ply: u32,
    mapper: SpectatorActionMode,
    obs_gen: DefaultObservationGenerator,
    move_history: Vec<(usize, String)>, // (action_index, move_notation)
}

#[pymethods]
impl SpectatorEnv {
    /// Create a new SpectatorEnv.
    ///
    /// Args:
    ///     max_ply: Positive maximum number of plies before the game ends (default 500).
    ///     action_mode: "default" (13527 actions) or "spatial" (11259, matches CNN policy head).
    #[new]
    #[pyo3(signature = (max_ply = 500, action_mode = "default"))]
    pub fn new(max_ply: u32, action_mode: &str) -> PyResult<Self> {
        if max_ply == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "max_ply must be positive",
            ));
        }
        let mapper = match action_mode {
            "default" => SpectatorActionMode::Default(DefaultActionMapper),
            "spatial" => SpectatorActionMode::Spatial(SpatialActionMapper::new()),
            other => {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "Unknown action_mode '{}'. Valid: 'default', 'spatial'",
                    other
                )));
            }
        };
        Ok(SpectatorEnv {
            game: GameState::with_max_ply(max_ply),
            max_ply,
            mapper,
            obs_gen: DefaultObservationGenerator::new(),
            move_history: Vec::new(),
        })
    }

    /// Create a SpectatorEnv from a SFEN string.
    ///
    /// Args:
    ///     sfen: SFEN position string.
    ///     max_ply: Positive maximum plies before truncation (default 500).
    ///
    /// Raises ValueError if the SFEN is invalid.
    #[staticmethod]
    #[pyo3(signature = (sfen, max_ply = None, action_mode = "default"))]
    pub fn from_sfen(sfen: &str, max_ply: Option<u32>, action_mode: &str) -> PyResult<Self> {
        let max_ply = max_ply.unwrap_or(500);
        if max_ply == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "max_ply must be positive",
            ));
        }
        let mapper = match action_mode {
            "default" => SpectatorActionMode::Default(DefaultActionMapper),
            "spatial" => SpectatorActionMode::Spatial(SpatialActionMapper::new()),
            other => {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "Unknown action_mode '{}'. Valid: 'default', 'spatial'",
                    other
                )));
            }
        };
        let mut game = GameState::from_sfen(sfen, max_ply)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("invalid SFEN: {e}")))?;
        game.check_termination();
        Ok(SpectatorEnv {
            game,
            max_ply,
            mapper,
            obs_gen: DefaultObservationGenerator::new(),
            move_history: Vec::new(),
        })
    }

    /// Reset game to startpos, clear move history, return state dict.
    pub fn reset(&mut self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        self.game = GameState::with_max_ply(self.max_ply);
        self.move_history.clear();
        self.to_dict(py)
    }

    /// Apply an action to the game.
    ///
    /// Raises RuntimeError if the game is already over.
    /// Returns the new state dict.
    pub fn step(&mut self, py: Python<'_>, action: usize) -> PyResult<Py<PyDict>> {
        if self.game.result.is_terminal() {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "Cannot step: game is already over. Call reset() to start a new game.",
            ));
        }

        let perspective = self.game.position.current_player;
        let mv = self
            .mapper
            .decode(action, perspective)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let legal_moves = self.game.legal_moves();
        if !legal_moves.contains(&mv) {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(format!(
                "action index {} is not legal for current position",
                action
            )));
        }

        let notation = move_notation(mv, &self.game.position, &legal_moves);
        self.move_history.push((action, notation));

        self.game.make_move(mv);
        self.game.check_termination();

        self.to_dict(py)
    }

    /// Return current state as a rich Python dict suitable for JSON serialization.
    ///
    /// Keys:
    /// - `board`: list of 81 elements, each None or `{"type": str, "color": str, "promoted": bool, "row": int, "col": int}`
    /// - `hands`: `{"black": {"pawn": N, ...}, "white": {...}}`
    /// - `current_player`: "black" or "white"
    /// - `ply`: int
    /// - `is_over`: bool
    /// - `result`: "in_progress" / "checkmate" / "repetition" / "perpetual_check" / "impasse" / "max_moves"
    /// - `winner`: "black" / "white" for decisive results, otherwise None
    /// - `sfen`: str
    /// - `in_check`: bool
    /// - `move_history`: list of `{"action": int, "notation": str}`
    pub fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let d_bound = build_spectator_dict(py, &self.game)?;
        let d = d_bound.bind(py);

        // Append move_history (SpectatorEnv-only)
        let history_list = PyList::empty(py);
        for (action_idx, notation) in &self.move_history {
            let hd = PyDict::new(py);
            hd.set_item("action", *action_idx as i64)?;
            hd.set_item("notation", notation.as_str())?;
            history_list.append(hd)?;
        }
        d.set_item("move_history", history_list)?;

        Ok(d_bound)
    }

    /// Serialize current position to SFEN string.
    pub fn to_sfen(&self) -> String {
        self.game.position.to_sfen()
    }

    /// Return a (C, 9, 9) observation using the same generators as VecEnv.
    /// "default" gives 46 channels; "katago" gives 50, including check and
    /// repetition features from the full game history.
    ///
    /// The observation is generated from the current player's perspective,
    /// consistent with VecEnv observation format.
    #[pyo3(signature = (observation_mode = "default"))]
    pub fn get_observation<'py>(
        &self,
        py: Python<'py>,
        observation_mode: &str,
    ) -> PyResult<Py<PyArray3<f32>>> {
        let katago = KataGoObservationGenerator::new();
        let generator: &dyn ObservationGenerator = match observation_mode {
            "default" => &self.obs_gen,
            "katago" => &katago,
            _ => {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "Unknown observation_mode '{observation_mode}'. Valid: 'default', 'katago'"
                )));
            }
        };
        let channels = generator.channels();
        let mut buffer = vec![0.0_f32; channels * 81];
        let perspective = self.game.position.current_player;
        generator.generate(&self.game, perspective, &mut buffer);
        let array = buffer.to_pyarray(py);
        let shaped = array
            .reshape([channels, 9, 9])
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        Ok(shaped.unbind())
    }

    /// Return a list of legal action indices for the current position.
    pub fn legal_actions(&mut self) -> Vec<usize> {
        if self.game.result.is_terminal() {
            return Vec::new();
        }
        let perspective = self.game.position.current_player;
        let moves = self.game.legal_moves();
        moves
            .into_iter()
            .map(|mv| {
                self.mapper
                    .encode(mv, perspective)
                    .expect("legal move must be encodable")
            })
            .collect()
    }

    /// Return all legal moves for the current position as `(action_index, usi_string)` pairs.
    ///
    /// `action_index` is the same value that `legal_actions()` returns; iteration order matches
    /// `legal_actions()` element-for-element. `usi_string` is the USI-protocol representation
    /// (e.g., `"7g7f"`, `"8h2b+"`, `"P*5e"`).
    ///
    /// `&mut self` is required because the underlying move-legality check uses make/unmake
    /// internally; the position is logically unchanged on return.
    pub fn legal_moves_with_usi(&mut self) -> Vec<(usize, String)> {
        if self.game.result.is_terminal() {
            return Vec::new();
        }
        let perspective = self.game.position.current_player;
        let moves = self.game.legal_moves();
        moves
            .into_iter()
            .map(|mv| {
                let idx = self
                    .mapper
                    .encode(mv, perspective)
                    .expect("legal move must be encodable");
                (idx, move_usi(mv))
            })
            .collect()
    }

    // -----------------------------------------------------------------------
    // Property getters
    // -----------------------------------------------------------------------

    /// Whether the game has ended.
    #[getter]
    pub fn is_over(&self) -> bool {
        self.game.result.is_terminal()
    }

    /// Current player as a string: "black" or "white".
    #[getter]
    pub fn current_player(&self) -> &str {
        color_name(self.game.position.current_player)
    }

    /// Current ply count.
    #[getter]
    pub fn ply(&self) -> u32 {
        self.game.ply
    }

    /// Total number of actions in the action space.
    /// 13527 for "default", 11259 for "spatial".
    #[getter]
    pub fn action_space_size(&self) -> usize {
        self.mapper.action_space_size()
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::action_mapper::ActionMapper;
    use pyo3::Python;
    use shogi_core::{Color, GameState, HandPieceType, Move, Square};

    #[test]
    fn test_katago_observation_preserves_repetition_and_check_features() {
        let mut env =
            SpectatorEnv::from_sfen("4k4/4R4/9/9/9/9/9/9/4K4 w - 1", None, "default").unwrap();
        env.game.repetition_map.insert(env.game.position.hash, 2);
        pyo3::prepare_freethreaded_python();
        Python::with_gil(|py| {
            let env = Py::new(py, env).unwrap();
            let kwargs = PyDict::new(py);
            kwargs.set_item("observation_mode", "katago").unwrap();
            let result = env
                .bind(py)
                .call_method("get_observation", (), Some(&kwargs))
                .expect("spectator must support actual KataGo observations");
            let array = result.downcast::<PyArray3<f32>>().unwrap();
            let readonly = array.readonly();
            let values = readonly.as_slice().unwrap();
            assert_eq!(values.len(), 50 * 81);
            assert_eq!(values[44 * 81], 1.0);
            assert_eq!(values[48 * 81], 1.0);
            let default_result = env.bind(py).call_method0("get_observation").unwrap();
            let default_array = default_result.downcast::<PyArray3<f32>>().unwrap();
            let default_readonly = default_array.readonly();
            let default_values = default_readonly.as_slice().unwrap();
            assert_eq!(default_values.len(), 46 * 81);
            assert_eq!(default_values[44 * 81], 0.0);
        });
    }

    #[test]
    fn test_constructor_rejects_zero_ply_limit() {
        assert!(SpectatorEnv::new(0, "default").is_err());
        assert!(
            SpectatorEnv::from_sfen("4k4/9/9/9/9/9/9/9/4K4 b - 1", Some(0), "default",).is_err()
        );
    }

    #[test]
    fn test_from_sfen_adjudicates_an_already_mated_position() {
        let mut env =
            SpectatorEnv::from_sfen("Kr7/1g7/9/9/9/9/9/9/8k b - 1", None, "default").unwrap();
        assert!(env.is_over());
        assert!(env.legal_actions().is_empty());
        assert!(env.legal_moves_with_usi().is_empty());
    }

    #[test]
    fn test_legal_action_apis_are_empty_after_a_ply_limit() {
        let mut env = SpectatorEnv::new(1, "spatial").unwrap();
        let mv = env.game.legal_moves()[0];
        env.game.make_move(mv);
        env.game.check_termination();
        assert!(env.is_over());
        assert!(env.legal_actions().is_empty());
        assert!(env.legal_moves_with_usi().is_empty());
    }

    // -----------------------------------------------------------------------
    // SpectatorEnv internal logic tests (no Python needed)
    // -----------------------------------------------------------------------

    /// Test that a new SpectatorEnv starts at ply 0 and is not over.
    #[test]
    fn test_spectator_env_initial_state() {
        // We can't call #[new] directly without Python, but we can test
        // the GameState that backs it.
        let game = GameState::with_max_ply(500);
        assert_eq!(game.ply, 0);
        assert!(!game.result.is_terminal());
        assert_eq!(game.position.current_player, Color::Black);
    }

    /// Test from_sfen with valid startpos.
    #[test]
    fn test_spectator_env_from_sfen_valid() {
        let sfen = "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1";
        let game = GameState::from_sfen(sfen, 500).expect("valid SFEN should parse");
        assert_eq!(game.ply, 0);
        assert_eq!(game.position.current_player, Color::Black);
    }

    /// Test from_sfen with invalid string.
    #[test]
    fn test_spectator_env_from_sfen_invalid() {
        let result = GameState::from_sfen("garbage sfen string", 500);
        assert!(result.is_err(), "Invalid SFEN should return error");
    }

    /// Test that stepping increments ply and flips player.
    #[test]
    fn test_spectator_env_step_increments_ply() {
        let mut game = GameState::with_max_ply(500);
        let mapper = DefaultActionMapper;

        let legal = game.legal_moves();
        assert!(!legal.is_empty());
        let mv = legal[0];
        let action = mapper.encode(mv, game.position.current_player).unwrap();

        // Decode and apply
        let perspective = game.position.current_player;
        let decoded = <DefaultActionMapper as ActionMapper>::decode(&mapper, action, perspective)
            .expect("decode should succeed");
        game.make_move(decoded);

        assert_eq!(game.ply, 1);
        assert_eq!(game.position.current_player, Color::White);
    }

    #[test]
    fn test_spectator_step_rejects_illegal_drop() {
        let mut env = SpectatorEnv {
            game: GameState::with_max_ply(500),
            max_ply: 500,
            mapper: SpectatorActionMode::Default(DefaultActionMapper),
            obs_gen: DefaultObservationGenerator::new(),
            move_history: Vec::new(),
        };
        let illegal_drop = Move::Drop {
            to: Square::from_row_col(4, 4).unwrap(),
            piece_type: HandPieceType::Pawn,
        };
        let action = DefaultActionMapper
            .encode(illegal_drop, Color::Black)
            .expect("drop should be encodable");

        pyo3::prepare_freethreaded_python();
        Python::with_gil(|py| {
            let err = env.step(py, action).expect_err("illegal drop must error");
            assert!(
                err.to_string().contains("not legal"),
                "unexpected error: {}",
                err
            );
        });
    }

    /// Verify legal_moves_with_usi() matches legal_actions() in order and content.
    #[test]
    fn test_legal_moves_with_usi_ordering_matches_legal_actions() {
        let mut env = SpectatorEnv {
            game: GameState::with_max_ply(500),
            max_ply: 500,
            mapper: SpectatorActionMode::Default(DefaultActionMapper),
            obs_gen: DefaultObservationGenerator::new(),
            move_history: Vec::new(),
        };

        let actions = env.legal_actions();
        let pairs = env.legal_moves_with_usi();

        assert_eq!(actions.len(), 30, "Startpos should have 30 legal actions");
        assert_eq!(
            pairs.len(),
            30,
            "legal_moves_with_usi should also yield 30 entries"
        );
        assert_eq!(actions.len(), pairs.len(), "lengths must match");

        for (i, (a, (idx, usi))) in actions.iter().zip(pairs.iter()).enumerate() {
            assert_eq!(
                *a, *idx,
                "action index mismatch at position {}: legal_actions={}, legal_moves_with_usi={}",
                i, a, idx
            );
            assert!(
                !usi.is_empty(),
                "USI string at position {} must be non-empty",
                i
            );
            assert_eq!(
                usi.len(),
                4,
                "USI at position {} should be length 4 at startpos (no promotion), got {:?}",
                i,
                usi
            );
            assert!(
                !usi.contains('*'),
                "USI at position {} must not contain '*' at startpos (no drops), got {:?}",
                i,
                usi
            );
        }
    }

    /// Test that legal_actions at startpos returns 30 entries.
    #[test]
    fn test_spectator_env_legal_actions_count() {
        let mut game = GameState::with_max_ply(500);
        let mapper = DefaultActionMapper;
        let perspective = game.position.current_player;

        let legal = game.legal_moves();
        let actions: Vec<usize> = legal
            .iter()
            .map(|mv| mapper.encode(*mv, perspective).unwrap())
            .collect();

        assert_eq!(actions.len(), 30, "Startpos should have 30 legal actions");

        // All action indices should be unique
        let unique: std::collections::HashSet<usize> = actions.iter().copied().collect();
        assert_eq!(unique.len(), 30, "All 30 action indices should be unique");
    }

    /// After a game reaches terminal state, verify is_terminal() returns true.
    #[test]
    fn test_spectator_env_game_over_detection() {
        // Use max_ply=0 to immediately end the game
        let mut game = GameState::with_max_ply(0);
        game.check_termination();
        assert!(
            game.result.is_terminal(),
            "Game with max_ply=0 should be over"
        );
    }
}
