import unittest
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_engine_runtime import er


def access(moves):
    return {'factible': all(m <= 3 for m in moves),
            'entregas_con_exceso': [i for i, m in enumerate(moves) if m > 3],
            'movimientos_max': max(moves), 'plan': [{'movimientos': m} for m in moves]}


class RescueGuaranteeTests(unittest.TestCase):
    def test_fewer_exceptions_cannot_increase_worst_stop(self):
        self.assertFalse(er._acepta_rescate(access([15, 4]), access([19, 0]), 100, 100, 100))

    def test_lower_max_cannot_increase_exception_count(self):
        self.assertFalse(er._acepta_rescate(access([8, 0]), access([4, 4]), 100, 100, 100))

    def test_distance_guard_is_original_not_compounded(self):
        self.assertTrue(er._acepta_rescate(access([8]), access([6]), 100, 104, 100))
        self.assertFalse(er._acepta_rescate(access([6]), access([2]), 104, 108, 100))

    def test_strict_improvement_and_boundary(self):
        self.assertTrue(er._acepta_rescate(access([8]), access([3]), 100, 105, 100))
        self.assertFalse(er._acepta_rescate(access([3]), access([3]), 100, 100, 100))
        self.assertFalse(er._acepta_rescate(access([8]), None, 100, 90, 100))

    def test_rejects_new_unresolved_order(self):
        candidate = access([1]); candidate['entregas_sin_orden'] = [1]
        self.assertFalse(er._acepta_rescate(access([8]), candidate, 100, 100, 100))


if __name__ == '__main__':
    unittest.main()
