import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


WORKFLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/daily.yml").read_text(encoding="utf-8")


def _script(nome):
    etapa = WORKFLOW.split(f"      - name: {nome}\n", 1)[1].split("\n      - name:", 1)[0]
    linhas = re.search(r"^        run: \|\n((?: {10}[^\n]*\n)+)", etapa, re.MULTILINE)[1]
    return "\n".join(linha[10:] for linha in linhas.splitlines())


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.bash = shutil.which("bash")
        if not self.bash and os.name == "nt":
            caminho_git = subprocess.check_output(["git", "--exec-path"], text=True).strip()
            candidato = Path(caminho_git).parents[2] / "bin" / "bash.exe"
            if candidato.is_file():
                self.bash = str(candidato)

    def test_agendamento_serializado_e_restrito_a_branch_padrao(self):
        self.assertIn('cron: "0 7 * * *"', WORKFLOW)
        self.assertIn("group: coleta-diaria-${{ github.ref }}", WORKFLOW)
        self.assertIn("cancel-in-progress: false", WORKFLOW)
        self.assertIn("github.ref == format('refs/heads/{0}', github.event.repository.default_branch)", WORKFLOW)
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", WORKFLOW)
        self.assertIn("if: steps.coleta.outputs.falha_total == 'true'", WORKFLOW)

    def _executar(self, script, **variaveis):
        if not self.bash:
            self.skipTest("Bash indisponível")
        return subprocess.run(
            [self.bash, "-e", "-c", script], capture_output=True, text=True,
            env={**os.environ, **variaveis}, timeout=10,
        )

    def test_saida_da_coleta_distingue_falha_total_de_erro_inesperado(self):
        with TemporaryDirectory() as pasta:
            saida = Path(pasta) / "saida"
            script = 'python() { return "$RESULTADO_TESTE"; }\n' + _script("Buscar vagas")
            for codigo, retorno, marca in (("0", 0, ""), ("2", 0, "falha_total=true\n"), ("1", 1, "")):
                with self.subTest(codigo=codigo):
                    saida.write_text("", encoding="utf-8")
                    resultado = self._executar(script, RESULTADO_TESTE=codigo, GITHUB_OUTPUT=saida.as_posix())
                    self.assertEqual(resultado.returncode, retorno, resultado.stderr)
                    self.assertEqual(saida.read_text(encoding="utf-8"), marca)

    def test_publicacao_em_falha_total_prepara_somente_diagnostico(self):
        script = _script("Salvar resultado no repositório (se mudou algo)")
        git_falso = '''
git() {
    printf "%s\\n" "$*"
    if [ "$1" = diff ]; then return 1; fi
}
date() { printf '2026-11-20'; }
'''
        for total in ("true", ""):
            with self.subTest(total=total):
                substituido = script.replace("${{ steps.coleta.outputs.falha_total }}", total)
                resultado = self._executar(git_falso + substituido)
                self.assertEqual(resultado.returncode, 0, resultado.stderr)
                self.assertIn("add -- data/coleta.json", resultado.stdout)
                self.assertEqual("add -- data/vagas.json data/vagas.md" in resultado.stdout, not total)
                self.assertEqual(resultado.stdout.splitlines().count("push"), 1)
