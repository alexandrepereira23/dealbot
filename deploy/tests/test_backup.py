import importlib.util
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("backup", Path(__file__).parents[1] / "scripts/backup-sqlite.py")
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class TestBackup(unittest.TestCase):
    def test_wal_ativo_restauracao_e_recusa_sobrescrita(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            estado = raiz / "estado"
            estado.mkdir(mode=0o700)
            copias = raiz / "backups"
            copias.mkdir(mode=0o700)
            origem = estado / "inbox.sqlite3"
            with closing(sqlite3.connect(origem)) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA user_version=7")
                for tabela in ("canais", "eventos", "midias"):
                    db.execute(f"CREATE TABLE {tabela}(id INTEGER PRIMARY KEY, checkpoint TEXT)")
                    db.execute(f"INSERT INTO {tabela} VALUES(1,'sintetico-congelado')")
                db.commit()
                self.assertTrue(Path(str(origem) + "-wal").exists())
                destino = copias / "snapshot.sqlite3"
                backup.salvar(origem, destino)
                db.execute("INSERT INTO eventos VALUES(2,'posterior')")
                db.commit()
                self.assertEqual(backup.verificar(destino)["estado"]["tabelas"]["eventos"]["quantidade"], 1)
                restaurado = raiz / "restaurado"
                backup.restaurar(destino, restaurado)
                self.assertEqual(backup.resumo(destino), backup.resumo(restaurado / "inbox.sqlite3"))
                with self.assertRaises(FileExistsError):
                    backup.restaurar(destino, restaurado)
                with self.assertRaises(ValueError):
                    backup.salvar(origem, destino)
                with destino.open("ab") as arquivo:
                    arquivo.write(b"alteracao")
                with self.assertRaises(ValueError):
                    backup.verificar(destino)

    def test_origem_ausente_nao_cria_banco(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            with self.assertRaises(ValueError):
                backup.salvar(raiz / "ausente.sqlite3", raiz / "copia.sqlite3")
            self.assertFalse((raiz / "ausente.sqlite3").exists())
            self.assertFalse((raiz / "copia.sqlite3").exists())
