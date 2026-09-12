using System.Net;
using System.Text.Json;
using PhotoAssistant.Api.Tests.Infrastructure;

namespace PhotoAssistant.Api.Tests;

[Collection(ApiCollection.Name)]
public sealed class HealthEndpointTests(ApiFactory factory)
{
    [Fact]
    public async Task Health_reports_the_database_as_reachable()
    {
        var client = factory.CreateClient();

        var response = await client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal("Healthy", document.RootElement.GetProperty("status").GetString());

        // The endpoint is only useful if it actually checks something, so assert
        // that the database check is present rather than just that we got a 200.
        var checks = document.RootElement.GetProperty("checks").EnumerateArray().ToList();
        Assert.Contains(checks, check => check.GetProperty("name").GetString() == "database");
    }
}
