using System.Diagnostics;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using PhotoAssistant.Api.Middleware;
using PhotoAssistant.Infrastructure;

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

app.UseExceptionHandler();
app.UseStatusCodePages();

if (app.Environment.IsDevelopment())
{
    app.MapOpenApi();
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
