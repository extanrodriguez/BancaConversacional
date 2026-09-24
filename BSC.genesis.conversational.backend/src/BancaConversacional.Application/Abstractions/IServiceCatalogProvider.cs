using BancaConversacional.Application.Models;

namespace BancaConversacional.Application.Abstractions;

public interface IServiceCatalogProvider
{
    IReadOnlyCollection<ServiceCatalogItem> GetAll();
}
