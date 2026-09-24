# Opción C — Abrir puertos 8440-8449 para tu IP en Azure NSG

## Datos del recurso

| Campo | Valor |
|-------|--------|
| Resource Group | `RG_BSC_PRJ_GENESIS` |
| VM | `vm-test002-genesis` |
| NSG | `vm-test002-genesis-nsg` |
| Regla | `Allow-QA-To-Dev-8440-8449` (prioridad **119**) |
| IP a agregar | `181.61.204.113/32` |
| Puertos | TCP **8440-8449** (incluye **8446** y **8447**) |

## Portal Azure (manual)

1. Ir a **vm-test002-genesis** → **Conectar** → **Configuración de red**
2. En **Reglas de puerto de entrada**, editar **Allow-QA-To-Dev-8440-8449**
3. En **Origen** → **Direcciones IP/CIDR** agregar:
   ```
   181.61.204.113/32
   ```
4. Mantener los existentes:
   - `172.31.83.208/29`
   - `192.168.150.4/32`
5. Guardar

> La regla **121 Deny-Other-Sources-8440-8449** debe quedar con prioridad **mayor** (número más alto) que la 119.

## Automático (Azure CLI)

```powershell
# 1. Login (solo una vez)
az login --use-device-code

# 2. Agregar tu IP actual a la regla
powershell -ExecutionPolicy Bypass -File .\deploy\azure\add_nsg_qa_ip.ps1
```

Con IP explícita:
```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\azure\add_nsg_qa_ip.ps1 -IpAddress 181.61.204.113
```

## Verificar

```powershell
curl http://20.127.25.24:8447/health
curl http://20.127.25.24:8446/health
```

Navegador: http://20.127.25.24:8447/pruebas

## Nota

Si tu IP pública cambia (ISP), vuelve a ejecutar el script o actualiza la regla en el portal.
