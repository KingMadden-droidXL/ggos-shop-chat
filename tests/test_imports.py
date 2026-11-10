import unittest


class TestImports(unittest.TestCase):
    def test_all_modules_import(self):
        import ggos.config  # noqa: F401
        import ggos.database  # noqa: F401
        import ggos.money_engine  # noqa: F401
        import ggos.boss  # noqa: F401
        import ggos.notifier  # noqa: F401
        import ggos.app  # noqa: F401

    def test_boss_accepts_db_path_kwarg(self):
        # This is the exact call server/app.py made that used to TypeError.
        from ggos.boss import BossAgent

        agent = BossAgent(db_path="/tmp/does-not-matter.db")
        self.assertEqual(agent.name, "GANGSTER_GOD")


if __name__ == "__main__":
    unittest.main()
