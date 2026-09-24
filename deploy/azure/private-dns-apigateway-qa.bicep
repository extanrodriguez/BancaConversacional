// Private DNS: apigateway-gen.qa.bsc.com.do → IP on-prem (Presentation Product QA)
// Vincula la zona a la VNet del S2S Azure↔BSC para que la VM cognitiva resuelva el FQDN.
//
targetScope = 'resourceGroup'

@description('Nombre de la zona DNS privada (FQDN padre).')
param zoneName string = 'qa.bsc.com.do'

@description('Nombre relativo del registro A (sin el sufijo de zona).')
param aRecordName string = 'apigateway-gen'

@description('IP privada del API gateway QA (resuelta on-prem / VPN).')
param aRecordIpv4Address string = '172.31.15.43'

@description('TTL del registro A en segundos.')
param aRecordTtl int = 300

@description('Nombre del vínculo VNet (recurso hijo de la zona).')
param vnetLinkName string = 'link-VNET_S2S_AZ_TO_BSC_GEN'

@description('Resource ID completo de la VNet a vincular.')
param virtualNetworkId string

@description('Habilitar registro automático de VMs en la zona.')
param registrationEnabled bool = false

@description('Tags opcionales.')
param tags object = {
  project: 'BSC-Genesis'
  purpose: 'presentation-product-dns'
}

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: zoneName
  location: 'global'
  tags: tags
}

resource aRecord 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZone
  name: aRecordName
  properties: {
    ttl: aRecordTtl
    aRecords: [
      {
        ipv4Address: aRecordIpv4Address
      }
    ]
  }
}

resource vnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZone
  name: vnetLinkName
  location: 'global'
  properties: {
    registrationEnabled: registrationEnabled
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

output privateDnsZoneId string = privateDnsZone.id
output privateDnsZoneName string = privateDnsZone.name
output fqdn string = '${aRecordName}.${zoneName}'
output resolvedIpv4Address string = aRecordIpv4Address
output virtualNetworkLinkId string = vnetLink.id
