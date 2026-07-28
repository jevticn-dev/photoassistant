using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Identity.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore;
using PhotoAssistant.Domain.Entities;
using PhotoAssistant.Infrastructure.Identity;

namespace PhotoAssistant.Infrastructure.Persistence;

/// <summary>
/// The single database context. Extends the Identity context so that accounts
/// and domain data share one connection, one transaction scope and one set of
/// migrations.
/// </summary>
public class PhotoAssistantDbContext(DbContextOptions<PhotoAssistantDbContext> options)
    : IdentityDbContext<ApplicationUser, IdentityRole<Guid>, Guid>(options)
{
    public DbSet<Photo> Photos => Set<Photo>();
    public DbSet<Example> Examples => Set<Example>();
    public DbSet<Look> Looks => Set<Look>();
    public DbSet<Project> Projects => Set<Project>();
    public DbSet<EditVersion> EditVersions => Set<EditVersion>();
    public DbSet<Choice> Choices => Set<Choice>();
    public DbSet<IngestStatus> IngestStatuses => Set<IngestStatus>();
    public DbSet<Job> Jobs => Set<Job>();

    protected override void OnModelCreating(ModelBuilder builder)
    {
        // Declared on the model as well as in the container init script: a
        // database created outside docker compose still needs the extension
        // before any vector column can be created.
        builder.HasPostgresExtension("vector");

        base.OnModelCreating(builder);

        builder.ApplyConfigurationsFromAssembly(typeof(PhotoAssistantDbContext).Assembly);
    }
}
