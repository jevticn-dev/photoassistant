using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using PhotoAssistant.Infrastructure.Persistence;

namespace PhotoAssistant.Api.Tests.Infrastructure;

/// <summary>
/// Boots the real application against a separate database.
///
/// The suffixed database keeps test accounts out of the development data while
/// still exercising the actual Postgres schema — an in-memory provider would
/// not, and this phase is precisely about proving that the schema works.
///
/// The lifetime methods are implemented explicitly: xUnit's IAsyncLifetime
/// declares them as Task, while WebApplicationFactory already has a DisposeAsync
/// returning ValueTask, and the two cannot share one signature.
/// </summary>
public sealed class ApiFactory : WebApplicationFactory<Program>, IAsyncLifetime
{
    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Development");

        builder.ConfigureAppConfiguration((_, configuration) =>
        {
            var settings = configuration.Build();

            configuration.AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["POSTGRES_DB"] = $"{settings["POSTGRES_DB"]}_test",
            });
        });
    }

    async Task IAsyncLifetime.InitializeAsync()
    {
        using var scope = Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();

        // Creates the test database if it is absent and brings it up to the
        // current migration — the same migrations the development database ran.
        await context.Database.MigrateAsync();
    }

    Task IAsyncLifetime.DisposeAsync() => DisposeAsync().AsTask();

    /// <summary>An address no previous test has used, so runs stay independent.</summary>
    public static string UniqueEmail() => $"test-{Guid.NewGuid():N}@example.com";
}
