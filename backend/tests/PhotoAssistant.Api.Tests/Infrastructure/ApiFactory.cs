using Amazon.S3;
using Amazon.S3.Util;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using PhotoAssistant.Infrastructure.Persistence;
using PhotoAssistant.Infrastructure.Storage;

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

        await EnsureBucketsAsync(scope.ServiceProvider);
    }

    /// <summary>
    /// Creates the buckets the upload path writes to, if they are not there.
    ///
    /// <para>
    /// The same responsibility as migrating: a test fixture brings its own
    /// preconditions. Locally compose has a one-shot container that makes them;
    /// in CI MinIO starts empty, and a developer pointing at a fresh instance
    /// would otherwise meet a NoSuchBucket from three layers down.
    /// </para>
    ///
    /// <para>
    /// Deliberately here and not in <c>S3ObjectStorage</c>. Creating a missing
    /// bucket on write would turn a misconfigured bucket name in production
    /// into a new, empty bucket — which looks exactly like data loss.
    /// </para>
    /// </summary>
    private static async Task EnsureBucketsAsync(IServiceProvider services)
    {
        var client = services.GetRequiredService<IAmazonS3>();
        var options = services.GetRequiredService<ObjectStorageOptions>();

        foreach (var bucket in new[]
                 {
                     options.OriginalsBucket,
                     options.DerivativesBucket,
                     options.ExportsBucket,
                 })
        {
            if (!await AmazonS3Util.DoesS3BucketExistV2Async(client, bucket))
            {
                await client.PutBucketAsync(bucket);
            }
        }
    }

    Task IAsyncLifetime.DisposeAsync() => DisposeAsync().AsTask();

    /// <summary>An address no previous test has used, so runs stay independent.</summary>
    public static string UniqueEmail() => $"test-{Guid.NewGuid():N}@example.com";
}
