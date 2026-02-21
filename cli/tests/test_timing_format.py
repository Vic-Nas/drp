"""
cli/tests/test_timing_format.py

Tests for cli/timing.py (Timer) and cli/format.py (ANSI color gating).

No network, no Django.
"""

import sys
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest


# ── Timer ─────────────────────────────────────────────────────────────────────

class TestTimer:
    def test_disabled_timer_checkpoint_is_noop(self):
        from cli.timing import Timer
        t = Timer(enabled=False)
        t.checkpoint('anything')   # must not raise or accumulate

    def test_disabled_timer_print_is_noop(self):
        from cli.timing import Timer
        t = Timer(enabled=False)
        t.checkpoint('x')
        # print() writes to stderr — capture it
        fake_err = StringIO()
        with patch('sys.stderr', fake_err):
            t.print()
        assert fake_err.getvalue() == ''

    def test_disabled_timer_instrument_is_noop(self):
        from cli.timing import Timer
        t = Timer(enabled=False)
        session = MagicMock()
        t.instrument(session)
        assert session.hooks.__setitem__.call_count == 0

    def test_enabled_timer_accumulates_checkpoints(self):
        from cli.timing import Timer
        t = Timer(enabled=True)
        t.checkpoint('step one')
        t.checkpoint('step two')
        assert len(t._steps) == 2
        assert t._steps[0][0] == 'step one'
        assert t._steps[1][0] == 'step two'

    def test_enabled_timer_checkpoint_ms_is_positive(self):
        from cli.timing import Timer
        import time
        t = Timer(enabled=True)
        time.sleep(0.01)
        t.checkpoint('wait')
        label, ms = t._steps[0]
        assert ms >= 0

    def test_enabled_timer_instrument_hooks_session(self):
        from cli.timing import Timer
        t = Timer(enabled=True)
        session = MagicMock()
        session.hooks = {'response': []}
        t.instrument(session)
        assert len(session.hooks['response']) == 1

    def test_instrument_accumulates_rtt(self):
        from cli.timing import Timer
        t = Timer(enabled=True)
        session = MagicMock()
        session.hooks = {'response': []}
        t.instrument(session)

        # Simulate a response event
        mock_res = MagicMock()
        mock_res.elapsed.total_seconds.return_value = 0.250
        session.hooks['response'][0](mock_res)

        assert t._total_rtt_ms == pytest.approx(250.0, abs=1)
        assert t._rtt_count == 1

    def test_print_outputs_total_row(self):
        from cli.timing import Timer
        t = Timer(enabled=True)
        t.checkpoint('connect')
        fake_err = StringIO()
        with patch('sys.stderr', fake_err):
            with patch('cli.format._ansi_on', return_value=False):
                t.print()
        output = fake_err.getvalue()
        assert 'total' in output

    def test_print_labels_single_rtt_as_server(self):
        from cli.timing import Timer
        t = Timer(enabled=True)
        session = MagicMock()
        session.hooks = {'response': []}
        t.instrument(session)
        mock_res = MagicMock()
        mock_res.elapsed.total_seconds.return_value = 0.1
        session.hooks['response'][0](mock_res)

        fake_err = StringIO()
        with patch('sys.stderr', fake_err):
            with patch('cli.format._ansi_on', return_value=False):
                t.print()
        assert 'server' in fake_err.getvalue()

    def test_print_labels_multiple_rtts_with_count(self):
        from cli.timing import Timer
        t = Timer(enabled=True)
        session = MagicMock()
        session.hooks = {'response': []}
        t.instrument(session)
        mock_res = MagicMock()
        mock_res.elapsed.total_seconds.return_value = 0.1
        # Two requests (e.g. auto_login + actual call)
        session.hooks['response'][0](mock_res)
        session.hooks['response'][0](mock_res)

        fake_err = StringIO()
        with patch('sys.stderr', fake_err):
            with patch('cli.format._ansi_on', return_value=False):
                t.print()
        assert '2 RTTs' in fake_err.getvalue()


# ── ANSI color gating ─────────────────────────────────────────────────────────

class TestAnsiGating:
    """
    _ansi_on() logic:
      NO_COLOR env var  → always False
      config ansi=False → always False
      config ansi=True + FORCE_COLOR → True (no tty check)
      config ansi=True + real tty    → True
      config ansi=True + no tty      → False
    """

    def _with_config(self, ansi: bool):
        return patch('cli.config.load', return_value={'ansi': ansi})

    def test_no_color_env_var_disables(self):
        from cli.format import _ansi_on
        with self._with_config(True):
            with patch.dict('os.environ', {'NO_COLOR': '1'}):
                assert _ansi_on() is False

    def test_config_ansi_false_disables(self):
        from cli.format import _ansi_on
        with self._with_config(False):
            with patch.dict('os.environ', {}, clear=False):
                assert _ansi_on() is False

    def test_force_color_enables_without_tty(self):
        from cli.format import _ansi_on
        with self._with_config(True):
            with patch.dict('os.environ', {'FORCE_COLOR': '1', 'NO_COLOR': ''}):
                # FORCE_COLOR bypasses tty check
                assert _ansi_on() is True

    def test_color_functions_return_plain_when_off(self):
        from cli.format import green, red, bold, dim, cyan, yellow
        with patch('cli.format._ansi_on', return_value=False):
            assert green('hello') == 'hello'
            assert red('hello') == 'hello'
            assert bold('hello') == 'hello'
            assert dim('hello') == 'hello'
            assert cyan('hello') == 'hello'
            assert yellow('hello') == 'hello'

    def test_color_functions_add_codes_when_on(self):
        from cli.format import green
        with patch('cli.format._ansi_on', return_value=True):
            result = green('hello')
        assert '\033[' in result
        assert 'hello' in result
        assert result.endswith('\033[0m')
