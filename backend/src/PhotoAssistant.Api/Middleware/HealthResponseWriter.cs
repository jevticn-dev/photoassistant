using System.Text.Json;
using Microsoft.Extensions.Diagnostics.HealthChecks;

namespace PhotoAssistant.Api.Middleware;

/// <summary>
/// Writes the health result as JSON instead of the default one-word body, so
/// that a failing dependency can be identified without reading the logs.
/// </summary>
internal static class HealthResponseWriter
{
    public static Task WriteAsync(HttpContext context, HealthReport report)
    {
        context.Response.ContentType = "application/json";

        var payload = new
        {
            status = report.Status.ToString(),
            durationMs = report.TotalDuration.TotalMilliseconds,
            checks = report.Entries.Select(entry => new
            {
                name = entry.Key,
                status = entry.Value.Status.ToString(),
                durationMs = entry.Value.Duration.TotalMilliseconds,

                // The exception message would describe our internals; the check
                // name is enough to say which dependency is unhappy.
                description = entry.Value.Description,
            }),
        };

        return context.Response.WriteAsync(JsonSerializer.Serialize(payload));
    }
}
