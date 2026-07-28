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

var app = builder.Build();

if (app.Environment.IsDevelopment())
{
    app.MapOpenApi();
}

app.UseAuthorization();

app.MapControllers();

app.Run();

/// <summary>
/// Exposed so that integration tests can drive the real application through
/// WebApplicationFactory. Top-level statements otherwise generate an internal
/// entry point that the test project cannot reach.
/// </summary>
public partial class Program;
