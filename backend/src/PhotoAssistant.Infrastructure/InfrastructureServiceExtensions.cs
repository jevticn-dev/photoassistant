using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using PhotoAssistant.Infrastructure.Persistence;

namespace PhotoAssistant.Infrastructure;

/// <summary>
/// The single entry point through which the API registers infrastructure.
/// Program.cs stays unaware of EF Core, Npgsql and the storage clients.
/// </summary>
public static class InfrastructureServiceExtensions
{
    public static IServiceCollection AddInfrastructure(
        this IServiceCollection services,
        IConfiguration configuration)
    {
        services.AddDbContext<PhotoAssistantDbContext>(options =>
            options
                .UseNpgsql(
                    BuildConnectionString(configuration),
                    npgsql => npgsql.UseVector())
                // Table and column names follow snake_case without every
                // property having to say so.
                .UseSnakeCaseNamingConvention());

        return services;
    }

    /// <summary>
    /// Assembles the connection string from individual settings instead of
    /// storing it whole. The same values drive docker compose, so there is one
    /// source of truth and no credential is written down twice.
    /// </summary>
    private static string BuildConnectionString(IConfiguration configuration)
    {
        var host = configuration["POSTGRES_HOST"]
                   ?? configuration["POSTGRES_HOST_LOCAL"]
                   ?? "localhost";
        var port = configuration["POSTGRES_PORT"] ?? "5432";
        var database = Required(configuration, "POSTGRES_DB");
        var user = Required(configuration, "POSTGRES_USER");
        var password = Required(configuration, "POSTGRES_PASSWORD");

        return $"Host={host};Port={port};Database={database};Username={user};Password={password}";
    }

    private static string Required(IConfiguration configuration, string key) =>
        configuration[key]
        ?? throw new InvalidOperationException(
            $"Configuration value '{key}' is missing. Copy .env.example to .env at the " +
            "repository root and fill it in.");
}
