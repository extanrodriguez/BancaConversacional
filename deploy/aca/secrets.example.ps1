# Plantilla de secretos para el admin (NO commitear valores reales).
# Uso: copiar a secrets.local.ps1 (gitignore) o pasar -OpenAiApiKey / -SearchApiKey.

# Suscripcion / RG objetivo
$SubscriptionId = "871a5b90-0204-450e-b968-3190e9143faf"
$ResourceGroup  = "rg-genesis-cognitive-mvp-eus"
$Location       = "eastus"

# Secretos (el admin los obtiene del vault interno / owners del proyecto)
$OpenAiApiKey = "<PEGAR_AZURE_OPENAI_API_KEY>"
$SearchApiKey = "<PEGAR_AZURE_SEARCH_API_KEY>"

# Endpoints ya van en el Bicep (no secretos):
#   OpenAI: https://testbsc0001.openai.azure.com/
#   Search: https://ai-search-genesis.search.windows.net  index=genesis-rag-index
