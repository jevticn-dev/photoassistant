using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace PhotoAssistant.Infrastructure.Persistence;

public static class DatabaseMigrator
{
    /// <summary>
    /// Applies pending migrations when APPLY_MIGRATIONS_ON_STARTUP is set.
    ///
    /// Off by default, and switched on only by docker compose. The phase gate
    /// requires the stack to come up from a clean state without manual steps,
    /// and a container that migrates itself is the smallest thing that achieves
    /// that — no extra service, no separate image with EF tooling.
    ///
    /// The flag exists because this is not what a real deployment should do:
    /// with more than one instance the migrations would race, and schema changes
    /// belong to a deliberate step rather than to whichever container starts
    /// first. Turning it off there is one environment variable.
    /// </summary>
    public static async Task ApplyMigrationsIfConfiguredAsync(
        this IServiceProvider services,
        IConfiguration configuration,
        CancellationToken cancellationToken = default)
    {
        if (!configuration.GetValue("APPLY_MIGRATIONS_ON_STARTUP", false))
        {
            return;
        }

        using var scope = services.CreateScope();

        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();
        var logger = scope.ServiceProvider
            .GetRequiredService<ILoggerFactory>()
            .CreateLogger(nameof(DatabaseMigrator));

        var pending = (await context.Database.GetPendingMigrationsAsync(cancellationToken)).ToArray();

        if (pending.Length == 0)
        {
            logger.LogInformation("Database schema is up to date");
            return;
        }

        logger.LogInformation(
            "Applying {Count} pending migration(s): {Migrations}",
            pending.Length,
            string.Join(", ", pending));

        await context.Database.MigrateAsync(cancellationToken);

        logger.LogInformation("Migrations applied");
    }
}
