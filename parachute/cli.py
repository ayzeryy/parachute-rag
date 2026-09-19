from __future__ import annotations

import argparse
from collections.abc import Callable

from dotenv import load_dotenv

from .agents import RequestContext
from .factory import build_specialists


def run_cli(name: str, builder: Callable[[dict[str, object]], object]) -> None:
    parser = argparse.ArgumentParser(description=f"Parachute S.A. - {name}")
    parser.add_argument("--cliente", default="Cliente")
    parser.add_argument(
        "--tandem-experimentado",
        action="store_true",
        help="Permite reservar cuando el diagnóstico sea marginal.",
    )
    args = parser.parse_args()
    load_dotenv()
    system = builder(build_specialists())
    print(f"\nParachute S.A. - arquitectura {name}")
    print("Para reservar incluye una fecha AAAA-MM-DD. Escribe Bye para salir.\n")
    while True:
        try:
            message = input("Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAgente: ¡Hasta luego!")
            return
        if message.casefold() == "bye":
            print("Agente: ¡Hasta luego!")
            return
        if not message:
            continue
        context = RequestContext(
            message,
            customer=args.cliente,
            experienced_tandem=args.tandem_experimentado,
        )
        try:
            print(f"Agente: {system.run(context)}\n")  # type: ignore[union-attr]
        except Exception as exc:
            print(f"Agente: No pude completar la solicitud: {exc}\n")
