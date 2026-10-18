from __future__ import annotations

import argparse
from collections.abc import Sequence

from dotenv import load_dotenv

from config import demo_appointments_db

from .demo import DemoCalendar, list_demo_appointments, reset_demo_appointments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Consulta y reinicia exclusivamente los datos de MODO DEMO."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "dates",
        help="Muestra las fechas relativas y sus escenarios meteorológicos.",
    )
    commands.add_parser(
        "appointments",
        help="Lista las citas guardadas en la SQLite demo.",
    )
    reset = commands.add_parser(
        "reset",
        help="Elimina las citas demo sin borrar el archivo ni su marca.",
    )
    reset.add_argument(
        "--confirm",
        action="store_true",
        help="Confirmación obligatoria para eliminar las citas demo.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "dates":
            print("MODO DEMO — calendario America/Guatemala")
            for item in DemoCalendar().days():
                print(
                    f"{item.scenario.value}: {item.date.isoformat()} — "
                    f"{item.description}"
                )
            return 0

        database = demo_appointments_db()
        print(f"Base demo efectiva: {database}")
        if args.command == "appointments":
            rows = list_demo_appointments(database)
            if not rows:
                print("No hay citas demo.")
                return 0
            for appointment_id, customer, requested, condition, created_at in rows:
                print(
                    f"#{appointment_id} | {customer} | {requested} | "
                    f"{condition} | {created_at}"
                )
            return 0

        if not args.confirm:
            print("Reinicio cancelado: añade --confirm para borrar citas demo.")
            return 2
        deleted = reset_demo_appointments(database)
        print(f"Citas demo eliminadas: {deleted}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Error de configuración demo: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
