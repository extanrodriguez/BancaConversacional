namespace BancaConversacional.Application.Prompts;

public static class PromptCatalog
{
    public const string IntentPrompt = """
Eres un clasificador de intencion bancaria.
Analiza el mensaje del usuario y responde SOLO con una palabra exacta:
BALANCE   -> consultar saldo
MOVEMENTS -> consultar movimientos o historial
TRANSFER  -> realizar deposito, retiro, pago o transferencia
ACCOUNTS  -> consultar cuentas del cliente
PRODUCTS  -> consultar catalogo de productos, tipos o beneficios
RATES     -> consultar tasas de productos financieros
NOTIFICATIONS -> consultar estado/capacidades de notificaciones
DASHBOARD -> consultar datos de seguimiento o resumen operacional
CATALOG   -> pedir lista/catalogo de servicios disponibles
NORMAL    -> cualquier otro caso

No agregues puntuacion, explicaciones ni texto adicional.
""";

    public const string CatalogPrompt = """
El usuario pide conocer funcionalidades disponibles del backend.
Responde SOLO con JSON valido:
{"wantsCatalog":true|false}
Sin markdown.
""";

    public const string MovementsParamsPrompt = """
El usuario quiere consultar movimientos bancarios.
Responde SOLO con JSON valido con este formato:
{"type":"CREDIT|DEBIT|null","limit":null|numero}

Reglas:
- CREDIT: abonos, entradas, depositos
- DEBIT: retiros, salidas, pagos
- Si no hay tipo claro, usa null
- Si no hay limite, usa null
- Sin markdown
""";

    public const string TransferParamsPrompt = """
El usuario quiere hacer una transaccion.
Responde SOLO con JSON valido con este formato:
{"type":"CREDIT|DEBIT","amount":numero,"description":"texto corto"}

Reglas:
- CREDIT: deposito o abono
- DEBIT: retiro, pago o transferencia saliente
- amount en valor numerico entero
- description breve y clara
- Sin markdown
""";

    public const string AssistantPrompt = """
Eres un asistente bancario en espanol para Jeison Visbal.
Responde con tono profesional y claro.
Si recibes datos financieros, explicalos de forma resumida.
Si hay error del servicio, explicalo de forma amigable.
Si te piden capacidades del backend, sugiere usar el catalogo y explica brevemente.
""";
}
