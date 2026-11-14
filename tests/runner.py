"""
Executor de testes com resumo visual em português.

Uso:
    python -m tests.runner              # testes offline (padrão)
    python -m tests.runner offline      # testes offline
    RUN_INTEGRATION=1 python -m tests.runner integration  # serviços reais
    python -m tests.runner all          # integração pulada sem autorização
    python -m tests.runner tests.unit.test_mapper

Cada teste imprime uma linha com o resultado e o tempo. No fim é
mostrado um resumo por módulo e um total geral.
"""

import os
import sys
import time
import unittest


USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"


def paint(text: str, color: str) -> str:
    if not USE_COLOR:
        return text
    return f"{color}{text}{RESET}"


STATUS_STYLE = {
    "ok": ("[ OK ]", GREEN),
    "falha": ("[FALHA]", RED),
    "erro": ("[ERRO]", RED),
    "pulado": ("[PULADO]", YELLOW),
    "xfail": ("[XFAIL]", YELLOW),
    "xpass": ("[XPASS]", YELLOW),
}


class VisualResult(unittest.TextTestResult):
    """
    Resultado de teste que imprime uma linha por teste.
    """

    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.results: list[tuple[str, str, float]] = []
        self._started: dict[str, float] = {}

    def startTest(self, test):
        self._started[test.id()] = time.perf_counter()
        super().startTest(test)

    def _record(self, test, status: str) -> None:
        elapsed = time.perf_counter() - self._started.pop(
            test.id(),
            time.perf_counter(),
        )

        self.results.append((test.id(), status, elapsed))

        label, color = STATUS_STYLE[status]

        self.stream.writeln(
            f"  {paint(label, color)}  "
            f"{test.id()}  "
            f"{paint(f'{elapsed * 1000:.1f} ms', CYAN)}"
        )
        self.stream.flush()

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "ok")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "falha")

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "erro")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "pulado")
        self.stream.writeln(f"           Motivo: {reason}")

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test, "xfail")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, "xpass")


def module_of(test_id: str) -> str:
    parts = test_id.split(".")

    if len(parts) >= 3:
        return ".".join(parts[:-2])

    return test_id


def build_suite(names: list[str]) -> unittest.TestSuite:
    loader = unittest.TestLoader()

    if not names:
        names = ["offline"]

    suites = []

    for name in names:

        if name == "offline":
            directories = ["tests/unit"]

        elif name == "integration":
            directories = ["tests/integration"]

        elif name == "all":
            directories = ["tests/unit", "tests/integration"]
        else:
            if name.startswith(("tests.legacy", "tests.test_bootstrap")):
                raise ValueError("Bootstrap legado está fora da suíte ativa.")
            suites.append(loader.loadTestsFromName(name))
            continue

        for directory in directories:
            suites.append(loader.discover(
                directory, pattern="test*.py", top_level_dir=".",
            ))

    return unittest.TestSuite(suites)


def print_header(total: int) -> None:
    line = "=" * 70

    print(paint(line, BOLD))
    print(paint("EXECUÇÃO DE TESTES — MoRHInGA ETL Worker", BOLD))
    print(paint(line, BOLD))
    print(f"Testes encontrados: {total}")
    print(paint("-" * 70, BOLD))


def print_summary(result: VisualResult, elapsed: float) -> None:
    line = "=" * 70

    totals = {
        status: 0
        for status in STATUS_STYLE
    }

    per_module: dict[str, dict[str, int]] = {}

    for test_id, status, _ in result.results:

        totals[status] += 1

        module = module_of(test_id)

        counts = per_module.setdefault(
            module,
            {name: 0 for name in STATUS_STYLE},
        )

        counts[status] += 1

    print()
    print(paint(line, BOLD))
    print(paint("RESUMO POR MÓDULO", BOLD))
    print(paint(line, BOLD))

    for module in sorted(per_module):

        counts = per_module[module]

        parts = []

        for status, (label, color) in STATUS_STYLE.items():

            if counts[status]:
                parts.append(
                    paint(
                        f"{label.strip('[]').strip()}: {counts[status]}",
                        color,
                    )
                )

        print(f"  {module}")
        print(f"    " + "  ".join(parts))

    total = len(result.results)

    ok = totals["ok"]

    problems = (
        totals["falha"]
        + totals["erro"]
        + totals["xpass"]
    )

    print()
    print(paint(line, BOLD))
    print(paint("RESUMO GERAL", BOLD))
    print(paint(line, BOLD))
    print(
        f"  Total: {total}  |  "
        f"{paint(f'OK: {ok}', GREEN)}  |  "
        f"{paint(f'Falhas: {totals['falha']}', RED)}  |  "
        f"{paint(f'Erros: {totals['erro']}', RED)}  |  "
        f"{paint(f'Pulados: {totals['pulado']}', YELLOW)}"
    )
    print(f"  Duração total: {paint(f'{elapsed:.3f} s', CYAN)}")

    if result.wasSuccessful() and result.testsRun > len(result.skipped):
        print()
        message = (
            "  ✔ TESTES EXECUTADOS PASSARAM (há testes pulados)"
            if result.skipped else "  ✔ TODOS OS TESTES PASSARAM"
        )
        print(paint(message, GREEN + BOLD))
    elif result.wasSuccessful():
        print()
        print(paint("  — NENHUM TESTE EXECUTADO (todos pulados ou suíte vazia)", YELLOW))
    else:
        print()
        print(
            paint(
                f"  ✘ {problems} TESTE(S) COM PROBLEMA",
                RED + BOLD,
            )
        )

    print(paint(line, BOLD))


def main(argv: list[str] | None = None) -> int:
    names = list(sys.argv[1:] if argv is None else argv)

    suite = build_suite(names)

    print_header(suite.countTestCases())

    runner = unittest.TextTestRunner(
        stream=sys.stdout,
        verbosity=0,
        resultclass=VisualResult,
    )

    started = time.perf_counter()
    result = runner.run(suite)
    elapsed = time.perf_counter() - started

    print_summary(result, elapsed)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
