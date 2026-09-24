@description('Genesis Cognitive — Container Apps (producción lab / QA)')
param location string = resourceGroup().location
param environmentName string = 'cae-genesis-eus'
param containerAppName string = 'genesis-api'
param acrName string = 'acrgenesis871a5b'
param redisName string = 'redis-genesis-lab'
param keyVaultName string = 'kv-genesis-cognitive'
param logAnalyticsName string = 'log-genesis-aca'
param imageTag string = 'latest'
param minReplicas int = 2
param maxReplicas int = 10
@description('false = solo ACR/Redis/KV/CAE (fase bootstrap antes de build)')
param deployContainerApp bool = true

// Endpoints reales del entorno cognitivo (no son secretos)
param azureOpenAiEndpoint string = 'https://testbsc0001.openai.azure.com/'
param azureOpenAiChatDeployment string = 'gpt-4o-mini'
param azureOpenAiEmbeddingDeployment string = 'text-embedding-3-small'
param azureOpenAiApiVersion string = '2024-12-01-preview'
param azureSearchEndpoint string = 'https://ai-search-genesis.search.windows.net'
param azureSearchIndex string = 'genesis-rag-index'

// Built-in role definition IDs
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var kvSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

// --- Log Analytics ---
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// --- ACR ---
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

// --- Redis ---
resource redis 'Microsoft.Cache/redis@2023-08-01' = {
  name: redisName
  location: location
  properties: {
    sku: {
      name: 'Basic'
      family: 'C'
      capacity: 1
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    redisConfiguration: {
      maxmemoryPolicy: 'allkeys-lru'
    }
  }
}

// --- Key Vault ---
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enabledForTemplateDeployment: true
  }
}

// --- Container Apps Environment ---
resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// --- Container App (requiere imagen en ACR + secretos en KV) ---
resource containerApp 'Microsoft.App/containerApps@2024-03-01' = if (deployContainerApp) {
  name: containerAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8445
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: 'system'
        }
      ]
      secrets: [
        {
          name: 'azure-openai-key'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/openai-api-key'
          identity: 'system'
        }
        {
          name: 'azure-search-key'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/search-api-key'
          identity: 'system'
        }
        {
          name: 'redis-connection'
          value: 'rediss://:${redis.listKeys().primaryKey}@${redis.properties.hostName}:6380/0'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'genesis-api'
          image: '${acr.properties.loginServer}/genesis-api:${imageTag}'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'GENESIS_HOST', value: '0.0.0.0' }
            { name: 'GENESIS_PORT', value: '8445' }
            { name: 'GENESIS_ENV', value: 'qa' }
            { name: 'GENESIS_SERVE_UI', value: 'true' }
            { name: 'GENESIS_FAQ_PATH', value: '/app/data/kb_faq_vf01.json' }
            { name: 'GENESIS_SQLITE_PATH', value: '/app/data/demo/modelo_bancario_genesis_v2.sqlite' }
            { name: 'GENESIS_KB_DIR', value: '/app/Knowledge_Base' }
            { name: 'GENESIS_REDIS_URL', secretRef: 'redis-connection' }
            { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAiEndpoint }
            { name: 'AZURE_OPENAI_API_KEY', secretRef: 'azure-openai-key' }
            { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: azureOpenAiChatDeployment }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: azureOpenAiEmbeddingDeployment }
            { name: 'AZURE_OPENAI_API_VERSION', value: azureOpenAiApiVersion }
            { name: 'AZURE_SEARCH_ENDPOINT', value: azureSearchEndpoint }
            { name: 'AZURE_SEARCH_API_KEY', secretRef: 'azure-search-key' }
            { name: 'AZURE_SEARCH_INDEX', value: azureSearchIndex }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8445
              }
              initialDelaySeconds: 30
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8445
              }
              initialDelaySeconds: 15
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

// --- RBAC: ACR pull + Key Vault Secrets User for the Container App MI ---
resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployContainerApp) {
  name: guid(acr.id, containerApp.id, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource kvSecretsUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployContainerApp) {
  name: guid(keyVault.id, containerApp.id, kvSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUserRoleId)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output containerAppFqdn string = deployContainerApp ? containerApp.properties.configuration.ingress.fqdn : ''
output acrLoginServer string = acr.properties.loginServer
output redisHostName string = redis.properties.hostName
output keyVaultUri string = keyVault.properties.vaultUri
output containerAppPrincipalId string = deployContainerApp ? containerApp.identity.principalId : ''
output containerAppNameOut string = containerAppName
output acrNameOut string = acr.name
output keyVaultNameOut string = keyVault.name
output caeNameOut string = cae.name
