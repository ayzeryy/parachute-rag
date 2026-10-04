# Diagramas de agentes - Hoja 5

Los tres programas reutilizan exactamente los mismos agentes e integraciones. Las
flechas sólidas representan delegación o *handoff*; la línea punteada representa
el acceso de un especialista a una integración externa.

## Arquitectura centralizada

```mermaid
flowchart TD
    U[Usuario] --> S[Supervisor central]
    S --> T[Agente de triaje]
    S --> F[Agente FAQ]
    S --> D[Agente de fecha]
    S --> W[Agente de clima]
    S --> R[Agente de seguridad]
    S --> A[Agente de agenda]
    F -.-> KB[(PostgreSQL + pgvector)]
    W -.-> OM[Open-Meteo]
    A -.-> DB[(SQLite)]
```

El supervisor conoce y controla la secuencia completa.

## Arquitectura jerárquica

```mermaid
flowchart TD
    U[Usuario] --> E[Manager ejecutivo]
    E --> T[Agente de triaje]
    E --> I[Manager de información]
    E --> O[Manager de operaciones]
    I --> F[Agente FAQ]
    O --> D[Agente de fecha]
    O --> W[Agente de clima]
    O --> R[Agente de seguridad]
    O --> A[Agente de agenda]
    F -.-> KB[(PostgreSQL + pgvector)]
    W -.-> OM[Open-Meteo]
    A -.-> DB[(SQLite)]
```

El manager raíz delega por dominio y el manager de operaciones coordina el flujo
de reserva.

## Arquitectura descentralizada

```mermaid
flowchart LR
    U[Usuario] --> T[Triaje]
    T -->|FAQ| F[FAQ]
    T -->|Cita| D[Fecha]
    D -->|handoff| W[Clima]
    W -->|handoff| R[Seguridad]
    R -->|handoff| A[Agenda]
    F -.-> KB[(pgvector)]
    W -.-> OM[Open-Meteo]
    A -.-> DB[(SQLite)]
```

No existe supervisor. Cada par conoce solamente el siguiente destino válido del
protocolo y le transfiere el contexto.
