using System.Diagnostics;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using PhotoAssistant.Api.Middleware;
using PhotoAssistant.Infrastructure;
using PhotoAssistant.Infrastructure.Persistence;
using Scalar.AspNetCore;

var builder = WebApplication.CreateBuilder(args);

// Load the repository-root .env so that `dotnet run`, `dotnet ef` and docker
// compose all read the same file. Inside a container the variables are already
// present in the environment, so the file simply is not there and this is a
// no-op.
DotNetEnv.Env.TraversePath().Load();
builder.Configuration.AddEnvironmentVariables();

builder.Services.AddControllers();
builder.Services.AddOpenApi();
builder.Services.AddInfrastructure(builder.Configuration);

// One error shape for the whole API: ProblemDetails covers validation
// failures, 401s, 404s and unhandled exceptions alike.
builder.Services.AddProblemDetails(options =>
    options.CustomizeProblemDetails = context =>
    {
        // Correlates a response the user is looking at with the log entry that
        // explains it.
        context.ProblemDetails.Extensions["traceId"] =
            Activity.Current?.Id ?? context.HttpContext.TraceIdentifier;
    });
builder.Services.AddExceptionHandler<GlobalExceptionHandler>();

var app = builder.Build();

await app.Services.ApplyMigrationsIfConfiguredAsync(builder.Configuration);

app.UseExceptionHandler();
app.UseStatusCodePages();

if (app.Environment.IsDevelopment())
{
    app.MapOpenApi();

    // The document alone is JSON nobody reads by hand, so it gets a reader.
    // Scalar rather than Swagger UI (phase 4, decision H): it is built for the
    // document .NET already generates, and it is one line with no attributes
    // sprinkled through the controllers.
    //
    // Inside the same IsDevelopment block as the document it renders — an API
    // browser on a production host is a map of every route for anyone who finds
    // it, and the pair must not drift apart.
    app.MapScalarApiReference(options => options
        .WithTitle("PhotoAssistant API")
        .WithTheme(ScalarTheme.BluePlanet));
}

app.UseAuthentication();
app.UseAuthorization();

app.MapControllers();

app.MapHealthChecks("/health", new HealthCheckOptions
{
    ResponseWriter = HealthResponseWriter.WriteAsync,
});

app.Run();

/// <summary>
/// Exposed so that integration tests can drive the real application through
/// WebApplicationFactory. Top-level statements otherwise generate an internal
/// entry point that the test project cannot reach.
/// </summary>
public partial class Program;
