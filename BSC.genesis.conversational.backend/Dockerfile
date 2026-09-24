# Build stage
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

COPY BancaConversacional.sln ./
COPY src/BancaConversacional.Api/BancaConversacional.Api.csproj src/BancaConversacional.Api/
COPY src/BancaConversacional.Application/BancaConversacional.Application.csproj src/BancaConversacional.Application/
COPY src/BancaConversacional.Domain/BancaConversacional.Domain.csproj src/BancaConversacional.Domain/
COPY src/BancaConversacional.Infrastructure/BancaConversacional.Infrastructure.csproj src/BancaConversacional.Infrastructure/

RUN dotnet restore BancaConversacional.sln

COPY . .
ARG APP_VERSION
RUN test -n "$APP_VERSION" && \
    numeric_version="${APP_VERSION%%[-+]*}" && \
    dotnet publish src/BancaConversacional.Api/BancaConversacional.Api.csproj -c Release -o /app/publish /p:UseAppHost=false \
    /p:Version="$APP_VERSION" \
    /p:PackageVersion="$APP_VERSION" \
    /p:InformationalVersion="$APP_VERSION" \
    /p:AssemblyVersion="${numeric_version}.0" \
    /p:FileVersion="${numeric_version}.0"

# Runtime stage
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
    
#COPY --from=build /app/publish .
COPY --from=build --chown=10001:10001 /app/publish .

ENV ASPNETCORE_URLS=http://+:8080
EXPOSE 8080

#COPY --from=build /app/publish .

# Ejecuta el contenedor con un UID/GID no-root
USER 10001:10001

ENTRYPOINT ["dotnet", "BancaConversacional.Api.dll"]
