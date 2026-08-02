using System.Text;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.IdentityModel.Tokens;
using PhotoAssistant.Application.Authentication;
using PhotoAssistant.Infrastructure.Identity;
using PhotoAssistant.Infrastructure.Persistence;

namespace PhotoAssistant.Infrastructure;

/// <summary>
/// The single entry point through which the API registers infrastructure.
/// Program.cs stays unaware of EF Core, Npgsql, Identity and the storage clients.
/// </summary>
public static class InfrastructureServiceExtensions
{
    public static IServiceCollection AddInfrastructure(
        this IServiceCollection services,
        IConfiguration configuration)
    {
        services.AddPersistence(configuration);
        services.AddAuthenticationServices(configuration);

        return services;
    }

    private static void AddPersistence(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddDbContext<PhotoAssistantDbContext>(options =>
            options
                .UseNpgsql(
                    BuildConnectionString(configuration),
                    npgsql => npgsql.UseVector())
                // Table and column names follow snake_case without every
                // property having to say so.
                .UseSnakeCaseNamingConvention());

        services.AddHealthChecks()
            .AddDbContextCheck<PhotoAssistantDbContext>(name: "database");
    }

    private static void AddAuthenticationServices(
        this IServiceCollection services,
        IConfiguration configuration)
    {
        var jwt = ReadJwtOptions(configuration);

        services.AddSingleton(jwt);
        services.AddSingleton(TimeProvider.System);
        services.AddScoped<JwtTokenGenerator>();
        services.AddScoped<IAuthenticationService, IdentityAuthenticationService>();

        services
            .AddIdentityCore<ApplicationUser>(options =>
            {
                options.User.RequireUniqueEmail = true;

                // Length is the setting that actually matters; the character
                // class rules mostly push people towards predictable
                // substitutions. Identity's defaults are kept otherwise.
                options.Password.RequiredLength = 8;

                options.Lockout.MaxFailedAccessAttempts = 5;
                options.Lockout.DefaultLockoutTimeSpan = TimeSpan.FromMinutes(15);
            })
            .AddRoles<IdentityRole<Guid>>()
            .AddEntityFrameworkStores<PhotoAssistantDbContext>();

        services
            .AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
            .AddJwtBearer(options =>
            {
                options.TokenValidationParameters = new TokenValidationParameters
                {
                    ValidateIssuer = true,
                    ValidateAudience = true,
                    ValidateLifetime = true,
                    ValidateIssuerSigningKey = true,
                    ValidIssuer = jwt.Issuer,
                    ValidAudience = jwt.Audience,
                    IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(jwt.Key)),

                    // Tokens expire when they say they expire. The five minute
                    // default grace period is a surprise nobody asked for.
                    ClockSkew = TimeSpan.Zero,
                };
            });

        services.AddAuthorization();
    }

    private static JwtOptions ReadJwtOptions(IConfiguration configuration) => new()
    {
        Key = Required(configuration, "JWT_KEY"),
        Issuer = Required(configuration, "JWT_ISSUER"),
        Audience = Required(configuration, "JWT_AUDIENCE"),
        ExpiryMinutes = int.TryParse(configuration["JWT_EXPIRY_MINUTES"], out var minutes)
            ? minutes
            : 60,
    };

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
