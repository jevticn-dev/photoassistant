using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using PhotoAssistant.Domain.Entities;

namespace PhotoAssistant.Infrastructure.Persistence.Configurations;

internal sealed class IngestStatusConfiguration : IEntityTypeConfiguration<IngestStatus>
{
    public void Configure(EntityTypeBuilder<IngestStatus> builder)
    {
        // EF pluralises the DbSet name into "ingest_statuses"; the manifest is
        // referred to as ingest_status everywhere else, including the plan.
        builder.ToTable("ingest_status");

        // Composite key: the manifest records progress per photo per step, and
        // one row per pair is exactly what makes a restart idempotent.
        builder.HasKey(status => new { status.PhotoReference, status.Step });

        builder.Property(status => status.PhotoReference).HasMaxLength(64).IsRequired();
        builder.Property(status => status.Step).HasMaxLength(64).IsRequired();

        builder.Property(status => status.Status)
            .HasConversion<string>()
            .HasMaxLength(32)
            .IsRequired();

        builder.Property(status => status.UpdatedAt)
            .HasDefaultValueSql("now()")
            .IsRequired();

        // A restart asks "which rows of this step are not done yet".
        builder.HasIndex(status => new { status.Step, status.Status });
    }
}
