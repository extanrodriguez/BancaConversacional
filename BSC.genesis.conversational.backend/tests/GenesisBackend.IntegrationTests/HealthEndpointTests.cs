using System.Net;
using System.Threading.Tasks;
using Xunit;

namespace GenesisBackend.IntegrationTests;

public class HealthEndpointTests : IClassFixture<Microsoft.AspNetCore.Mvc.Testing.WebApplicationFactory<Api.Program>>
{
    private readonly Microsoft.AspNetCore.Mvc.Testing.WebApplicationFactory<Api.Program> _factory;

    public HealthEndpointTests(Microsoft.AspNetCore.Mvc.Testing.WebApplicationFactory<Api.Program> factory)
    {
        _factory = factory;
    }

    [Theory]
    [InlineData("/health")]
    [InlineData("/health/live")]
    [InlineData("/health/ready")]
    public async Task HealthEndpoints_ReturnOk(string url)
    {
        var client = _factory.CreateClient();
        var response = await client.GetAsync(url);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }
}
