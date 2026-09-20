using System.Text;
using Amazon.Runtime;
using Amazon.S3;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.IdentityModel.Tokens;
using PhotoAssistant.Application.Authentication;
using PhotoAssistant.Application.Photos;
using PhotoAssistant.Application.Projects;
using PhotoAssistant.Application.Storage;
using PhotoAssistant.Infrastructure.Identity;
using PhotoAssistant.Infrastructure.MlService;
using PhotoAssistant.Infrastructure.Persistence;
using PhotoAssistant.Infrastructure.Storage;

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
        services.AddObjectStorage(configuration);
        services.AddMlService(configuration);
        services.AddPhotos();

        return services;
    }

    /// <summary>
    /// The upload use case and the one thing it needs persisted. The handler
    /// itself lives in Application; only its registration belongs here.
    /// </summary>
    private static void AddPhotos(this IServiceCollection services)
    {
        services.AddScoped<IPhotoUploadRepository, PhotoUploadRepository>();
        services.AddScoped<IPhotoRepository, PhotoRepository>();
        services.AddScoped<IChoiceRepository, ChoiceRepository>();
        services.AddScoped<IProjectRepository, ProjectRepository>();
        services.AddScoped<UploadPhotoHandler>();
        services.AddScoped<SuggestEditsHandler>();
        services.AddScoped<GetPhotoImageHandler>();
        services.AddScoped<RecordChoiceHandler>();
        services.AddScoped<GetProjectHandler>();
    }

    private static void AddObjectStorage(this IServiceCollection services, IConfiguration configuration)
    {
        // The neutral names are what compose injects, and they win. The
        // fallbacks are for running the API on the host, where the same MinIO
        // is reached at a different address and the credentials are still only
        // written down once, under the names the container image uses. This
        // mirrors POSTGRES_HOST / POSTGRES_HOST_LOCAL below, and what
        // pipeline/environment.py does on the Python side.
        var options = new ObjectStorageOptions
        {
            Endpoint = configuration["S3_ENDPOINT"]
                       ?? Required(configuration, "S3_ENDPOINT_LOCAL"),
            AccessKey = configuration["S3_ACCESS_KEY"]
                        ?? Required(configuration, "MINIO_ROOT_USER"),
            SecretKey = configuration["S3_SECRET_KEY"]
                        ?? Required(configuration, "MINIO_ROOT_PASSWORD"),
            Region = configuration["S3_REGION"] ?? "us-east-1",
            OriginalsBucket = Required(configuration, "S3_BUCKET_ORIGINALS"),
            DerivativesBucket = Required(configuration, "S3_BUCKET_DERIVATIVES"),
            ExportsBucket = Required(configuration, "S3_BUCKET_EXPORTS"),
        };

        services.AddSingleton(options);
        services.AddSingleton<IAmazonS3>(_ => new AmazonS3Client(
            new BasicAWSCredentials(options.AccessKey, options.SecretKey),
            new AmazonS3Config
            {
                ServiceURL = options.Endpoint,
                AuthenticationRegion = options.Region,

                // MinIO addresses buckets by path, not by subdomain. Left at the
                // default the SDK would ask for `bucket.minio:9000`, which does
                // not resolve inside compose and fails as a name lookup rather
                // than as a configuration mistake.
                ForcePathStyle = true,
            }));

        services.AddScoped<IObjectStorage, S3ObjectStorage>();
    }

    private static void AddMlService(this IServiceCollection services, IConfiguration configuration)
    {
        // Same reasoning as the storage endpoint: the compose name inside the
        // network, localhost from the host.
        var address = configuration["ML_SERVICE_URL"]
                      ?? Required(configuration, "ML_SERVICE_URL_LOCAL");

        services.AddHttpClient<IDerivativeGenerator, MlDerivativeGenerator>(client =>
        {
            client.BaseAddress = new Uri(address);

            // Deriving both sizes of a large photograph is real work, and the
            // default of 100 seconds is long enough that a stuck request would
            // hold a browser far past the point of usefulness.
            client.Timeout = TimeSpan.FromSeconds(30);
        });

        // Measured at p95 262 ms in phase 3, against a budget of 1,5 s (§B82).
        // Ten seconds is far above anything healthy and far below a browser
        // giving up on its own, so a stalled service fails as a message rather
        // than as a spinner nobody can explain.
        services.AddHttpClient<IRecommendationService, MlRecommendationService>(client =>
        {
            client.BaseAddress = new Uri(address);
            client.Timeout = TimeSpan.FromSeconds(10);
        });
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
