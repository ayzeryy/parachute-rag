from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "informe_hoja5.pdf"
NAVY = colors.HexColor("#102A43")
BLUE = colors.HexColor("#167D9A")
SKY = colors.HexColor("#D9F0F5")
GOLD = colors.HexColor("#F4B942")
INK = colors.HexColor("#243B53")
MUTED = colors.HexColor("#627D98")
LIGHT = colors.HexColor("#F4F7FA")


def register_fonts():
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/Arial.ttf"),
    ]
    bold_candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/Arialbd.ttf"),
    ]
    regular = next((path for path in candidates if path.exists()), None)
    bold = next((path for path in bold_candidates if path.exists()), None)
    if regular and bold:
        pdfmetrics.registerFont(TTFont("Report", regular))
        pdfmetrics.registerFont(TTFont("Report-Bold", bold))
        return "Report", "Report-Bold"
    return "Helvetica", "Helvetica-Bold"


FONT, FONT_BOLD = register_fonts()


class ArchitectureDiagram(Flowable):
    def __init__(self, kind, width=16.5 * cm, height=7.2 * cm):
        super().__init__()
        self.kind = kind
        self.width = width
        self.height = height

    def box(self, canvas, x, y, w, h, text, fill=SKY, small=False):
        canvas.setFillColor(fill)
        canvas.setStrokeColor(BLUE)
        canvas.roundRect(x, y, w, h, 6, fill=1, stroke=1)
        canvas.setFillColor(NAVY)
        canvas.setFont(FONT_BOLD, 7.5 if small else 9)
        canvas.drawCentredString(x + w / 2, y + h / 2 - 3, text)

    def arrow(self, canvas, x1, y1, x2, y2):
        canvas.setStrokeColor(MUTED)
        canvas.setFillColor(MUTED)
        canvas.setLineWidth(1.1)
        canvas.line(x1, y1, x2, y2)
        angle = 4
        if abs(x2 - x1) > abs(y2 - y1):
            sign = 1 if x2 > x1 else -1
            canvas.line(x2, y2, x2 - sign * angle, y2 + angle / 2)
            canvas.line(x2, y2, x2 - sign * angle, y2 - angle / 2)
        else:
            sign = 1 if y2 > y1 else -1
            canvas.line(x2, y2, x2 - angle / 2, y2 - sign * angle)
            canvas.line(x2, y2, x2 + angle / 2, y2 - sign * angle)

    def draw(self):
        c = self.canv
        if self.kind == "central":
            self.box(c, 6.0 * cm, 5.4 * cm, 4.5 * cm, 1.0 * cm, "Supervisor central", GOLD)
            specialists = ["Triaje", "FAQ", "Fecha", "Clima", "Seguridad", "Agenda"]
            for i, label in enumerate(specialists):
                x = (i % 3) * 5.4 * cm + 0.2 * cm
                y = (2.9 if i < 3 else 0.8) * cm
                self.box(c, x, y, 4.3 * cm, 0.9 * cm, label)
                self.arrow(c, 8.25 * cm, 5.4 * cm, x + 2.15 * cm, y + 0.9 * cm)
        elif self.kind == "hierarchical":
            self.box(c, 5.9 * cm, 5.5 * cm, 4.7 * cm, 0.9 * cm, "Manager ejecutivo", GOLD)
            self.box(c, 1.2 * cm, 3.6 * cm, 5.2 * cm, 0.9 * cm, "Manager de información")
            self.box(c, 10.1 * cm, 3.6 * cm, 5.2 * cm, 0.9 * cm, "Manager de operaciones")
            self.arrow(c, 8.25 * cm, 5.5 * cm, 3.8 * cm, 4.5 * cm)
            self.arrow(c, 8.25 * cm, 5.5 * cm, 12.7 * cm, 4.5 * cm)
            self.box(c, 1.7 * cm, 1.4 * cm, 4.2 * cm, 0.8 * cm, "FAQ")
            self.arrow(c, 3.8 * cm, 3.6 * cm, 3.8 * cm, 2.2 * cm)
            for i, label in enumerate(["Fecha", "Clima", "Seguridad", "Agenda"]):
                x = 8.1 * cm + (i % 2) * 4.2 * cm
                y = (2.0 if i < 2 else 0.6) * cm
                self.box(c, x, y, 3.3 * cm, 0.75 * cm, label, small=True)
                self.arrow(c, 12.7 * cm, 3.6 * cm, x + 1.65 * cm, y + 0.75 * cm)
        else:
            labels = ["Triaje", "Fecha", "Clima", "Seguridad", "Agenda"]
            for i, label in enumerate(labels):
                x = 0.1 * cm + i * 3.25 * cm
                self.box(c, x, 3.3 * cm, 2.45 * cm, 0.9 * cm, label, GOLD if i == 0 else SKY, True)
                if i:
                    self.arrow(c, x - 0.6 * cm, 3.75 * cm, x, 3.75 * cm)
            self.box(c, 0.1 * cm, 1.2 * cm, 2.45 * cm, 0.9 * cm, "FAQ", SKY, True)
            self.arrow(c, 1.3 * cm, 3.3 * cm, 1.3 * cm, 2.1 * cm)
            c.setFont(FONT, 7)
            c.setFillColor(MUTED)
            c.drawString(2.9 * cm, 4.0 * cm, "handoff")
            c.drawString(6.2 * cm, 4.0 * cm, "handoff")
            c.drawString(9.4 * cm, 4.0 * cm, "handoff")
            c.drawString(12.7 * cm, 4.0 * cm, "handoff")


def styles():
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title", parent=sample["Title"], fontName=FONT_BOLD,
            fontSize=25, leading=30, textColor=NAVY, alignment=TA_CENTER,
            spaceAfter=12,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=sample["Normal"], fontName=FONT,
            fontSize=12, leading=17, textColor=MUTED, alignment=TA_CENTER,
        ),
        "h1": ParagraphStyle(
            "H1", parent=sample["Heading1"], fontName=FONT_BOLD,
            fontSize=18, leading=22, textColor=NAVY, spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "H2", parent=sample["Heading2"], fontName=FONT_BOLD,
            fontSize=12, leading=15, textColor=BLUE, spaceBefore=8, spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "Body", parent=sample["BodyText"], fontName=FONT,
            fontSize=9.5, leading=14, textColor=INK, alignment=TA_JUSTIFY,
            spaceAfter=7,
        ),
        "small": ParagraphStyle(
            "Small", parent=sample["BodyText"], fontName=FONT,
            fontSize=8, leading=11, textColor=INK,
        ),
        "callout": ParagraphStyle(
            "Callout", parent=sample["BodyText"], fontName=FONT_BOLD,
            fontSize=10, leading=15, textColor=NAVY, alignment=TA_CENTER,
        ),
    }


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(SKY)
    canvas.line(2 * cm, 1.45 * cm, 19 * cm, 1.45 * cm)
    canvas.setFont(FONT, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(2 * cm, 1.05 * cm, "Parachute S.A. | Hoja de trabajo 5")
    canvas.drawRightString(19 * cm, 1.05 * cm, f"Página {doc.page}")
    canvas.restoreState()


def bullet(text, st):
    return Paragraph(f"• {text}", st["body"])


def architecture_page(st, title, kind, description, strengths, limitation):
    content = [Paragraph(title, st["h1"]), Paragraph(description, st["body"])]
    content += [Spacer(1, 4), ArchitectureDiagram(kind), Spacer(1, 5)]
    content += [
        Table(
            [
                [Paragraph("Fortaleza principal", st["small"]), Paragraph(strengths, st["small"])],
                [Paragraph("Limitación principal", st["small"]), Paragraph(limitation, st["small"])],
            ],
            colWidths=[4.2 * cm, 12.2 * cm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), LIGHT),
                    ("BOX", (0, 0), (-1, -1), 0.5, SKY),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, SKY),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            ),
        ),
        PageBreak(),
    ]
    return content


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    st = styles()
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4, rightMargin=2 * cm, leftMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=1.9 * cm,
        title="Parachute S.A. - Hoja de trabajo 5",
        author="Equipo de desarrollo",
    )
    story = [
        Spacer(1, 3.0 * cm),
        Paragraph("Sistemas multiagente para Parachute S.A.", st["title"]),
        Paragraph(
            "Comparación de orquestación centralizada, jerárquica y descentralizada",
            st["subtitle"],
        ),
        Spacer(1, 1.2 * cm),
        Table(
            [[Paragraph("HOJA 5", st["callout"])],
             [Paragraph("Clima, seguridad de salto, agenda y FAQs", st["subtitle"])]],
            colWidths=[13 * cm],
            rowHeights=[1.1 * cm, 1.2 * cm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), GOLD),
                ("BACKGROUND", (0, 1), (-1, 1), LIGHT),
                ("BOX", (0, 0), (-1, -1), 1, SKY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]),
        ),
        Spacer(1, 2.2 * cm),
        Paragraph(
            "Objetivo: resolver el mismo flujo funcional con tres formas de colaboración "
            "entre agentes, conservando una única implementación de las integraciones.",
            st["subtitle"],
        ),
        PageBreak(),
        Paragraph("1. Solución común", st["h1"]),
        Paragraph(
            "Los tres programas comparten seis especialistas: triaje, extracción de fecha, "
            "clima, seguridad, agenda y FAQs. WeatherService consulta Open-Meteo con las "
            "coordenadas 14.013722, -90.771611 y solicita temperatura máxima, precipitación "
            "acumulada, cobertura media de nubes, viento máximo y ráfagas máximas. La fecha "
            "debe estar entre hoy y el día 16 de la ventana, ambos inclusive.",
            st["body"],
        ),
        Paragraph("Reglas de aceptación", st["h2"]),
        bullet("Ideal: viento menor a 20 km/h, sin lluvia y nubes menores a 30%.", st),
        bullet("Marginal: viento entre 20 y 28 km/h o nubes entre 30% y 75%.", st),
        bullet("El viento marginal exige que el usuario declare un tándem experimentado.", st),
        bullet("Prohibido: viento mayor a 28 km/h, ráfagas mayores a 35 km/h, cualquier precipitación o nubes mayores a 75%.", st),
        Paragraph("Abstracciones para crecimiento", st["h2"]),
        Paragraph(
            "WeatherService, assess_weather y AppointmentRepository no conocen la "
            "arquitectura de orquestación. factory.build_specialists compone una vez las "
            "integraciones y entrega los mismos objetos a cada programa. Por eso un nuevo "
            "canal, regla o proveedor puede incorporarse sin reescribir las tres variantes.",
            st["body"],
        ),
        Paragraph("Decisión técnica", st["h2"]),
        Paragraph(
            "Las reglas que autorizan un salto son deterministas. Un LLM no decide si una "
            "condición es segura ni puede omitir una validación. El RAG anterior se conserva "
            "para FAQs; los handoffs de la variante descentralizada son explícitos y "
            "auditables. Esto mantiene compatibilidad con el cliente NVIDIA/OpenAI existente.",
            st["body"],
        ),
        PageBreak(),
    ]
    story += architecture_page(
        st,
        "2. Arquitectura centralizada",
        "central",
        "CentralSupervisor clasifica la solicitud y controla directamente toda la secuencia. "
        "Cada resultado vuelve al supervisor antes de invocar al siguiente especialista.",
        "Flujo simple, trazabilidad directa y un único lugar para políticas globales.",
        "El supervisor concentra conocimiento y se convierte en cuello de botella a medida que crecen los dominios.",
    )
    story += architecture_page(
        st,
        "3. Arquitectura jerárquica",
        "hierarchical",
        "ExecutiveManager delega por dominio. InformationManager atiende FAQs y "
        "OperationsManager coordina fecha, clima, seguridad y agenda.",
        "Escala mejor: cada manager encapsula un dominio y reduce la complejidad del nivel raíz.",
        "Agrega capas, más objetos y una ruta de coordinación un poco más larga.",
    )
    story += architecture_page(
        st,
        "4. Arquitectura descentralizada",
        "decentralized",
        "PeerNetwork no tiene supervisor. Triaje entrega la solicitud al primer par y "
        "cada agente hace handoff al siguiente usando el contexto acumulado.",
        "Bajo acoplamiento con un coordinador central y fácil sustitución de pares especializados.",
        "Es más difícil observar el flujo completo, evitar ciclos y aplicar políticas transversales.",
    )
    story += [
        Paragraph("5. Respuestas", st["h1"]),
        Paragraph("1. ¿Qué arquitectura resuelve mejor este problema? ¿Por qué?", st["h2"]),
        Paragraph(
            "La arquitectura jerárquica ofrece el mejor equilibrio para este caso. Hoy el "
            "flujo tiene dos dominios claros: información (FAQs) y operaciones (clima, "
            "seguridad y agenda). Un manager ejecutivo mantiene una interfaz única, mientras "
            "managers de dominio absorben el crecimiento anunciado por Parachute S.A. sin "
            "convertir al supervisor raíz en una clase monolítica. También facilita aplicar "
            "una política de seguridad común y observar quién autorizó cada reserva.",
            st["body"],
        ),
        Paragraph(
            "La centralizada también es una buena opción para el alcance actual: es la más "
            "simple de operar y depurar. Sin embargo, pierde atractivo cuando aumentan las "
            "funciones. La descentralizada demuestra handoffs correctamente, pero no es la "
            "primera elección en un proceso corto, secuencial y regulado, porque la gobernanza, "
            "la trazabilidad y el control de errores requieren trabajo adicional.",
            st["body"],
        ),
        Paragraph("2. ¿Es necesario utilizar un sistema multiagente? ¿Por qué?", st["h2"]),
        Paragraph(
            "No es estrictamente necesario. Un servicio convencional con módulos de RAG, "
            "clima, reglas y persistencia resolvería el requisito con menor costo operativo, "
            "menos latencia y pruebas más sencillas. Además, las reglas meteorológicas son "
            "deterministas y no se benefician de razonamiento autónomo.",
            st["body"],
        ),
        Paragraph(
            "Sí puede ser justificable como diseño evolutivo y como ejercicio académico. La "
            "separación por agentes crea límites claros de responsabilidad y permite que, en "
            "el futuro, reservas, soporte, pagos, notificaciones y logística evolucionen o "
            "escalen de manera independiente. La recomendación práctica es conservar las "
            "integraciones y políticas críticas como servicios deterministas, usando agentes "
            "para coordinación, lenguaje natural y delegación, no para reemplazar controles "
            "de seguridad.",
            st["body"],
        ),
        Spacer(1, 8),
        KeepTogether([
            Paragraph("Conclusión", st["h2"]),
            Table(
                [[Paragraph(
                    "Recomendación: arquitectura jerárquica para producción; centralizada "
                    "para un MVP; descentralizada cuando existan dominios realmente autónomos.",
                    st["callout"],
                )]],
                colWidths=[16.2 * cm],
                style=TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), SKY),
                    ("BOX", (0, 0), (-1, -1), 1, BLUE),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ]),
            ),
        ]),
        Spacer(1, 12),
        Paragraph("Referencias", st["h2"]),
        Paragraph(
            "Open-Meteo Forecast API: https://open-meteo.com/en/docs<br/>"
            "OpenAI Agents - manager agents as tools y handoffs: "
            "https://openai.github.io/openai-agents-python/agents/",
            st["small"],
        ),
    ]
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    print(OUTPUT)


if __name__ == "__main__":
    build()
