import unittest
from campus_story_index.parallel import map_bounded


class ParallelTests(unittest.TestCase):
    def test_all_results_are_returned_once_including_empty_input(self):
        self.assertCountEqual(map_bounded(lambda n: n * n, range(1000), 4),
                              [n * n for n in range(1000)])
        self.assertEqual(list(map_bounded(str, [], 4)), [])

    def test_failure_stops_consuming_the_release_queue(self):
        consumed = []
        def jobs():
            for number in range(100_000):
                consumed.append(number)
                yield number
        def fail(_):
            raise RuntimeError('upload failed')
        with self.assertRaisesRegex(RuntimeError, 'upload failed'):
            list(map_bounded(fail, jobs(), 4))
        self.assertLessEqual(len(consumed), 8)

    def test_rejects_invalid_worker_count(self):
        with self.assertRaises(ValueError):
            list(map_bounded(str, [], 0))
