using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using PhotoAssistant.Domain.Entities;
using Pgvector;

namespace PhotoAssistant.Infrastructure.Persistence.Configurations;

internal sealed class LookConfiguration : IEntityTypeConfiguration<Look>
{
    public void Configure(EntityTypeBuilder<Look> builder)
    {
        builder.HasKey(look => look.Id);

        builder.Property(look => look.Name).HasMaxLength(200).IsRequired();

        builder.Property(look => look.Edit)
            .HasColumnType("jsonb")
            .IsRequired();

        builder.Property(look => look.Source)
            .HasConversion<string>()
            .HasMaxLength(32)
            .IsRequired();

        builder.Property(look => look.Family).HasMaxLength(100);

        // Shadow property; see ExampleConfiguration. Dimension fixed in phase 2.
        builder.Property<Vector?>("StyleFingerprint").HasColumnType("vector");

        builder.Property(look => look.CreatedAt)
            .HasDefaultValueSql("now()")
            .IsRequired();

        // Personal looks are pulled into the candidate pool for their owner,
        // so they are filtered by owner on every recommendation.
        builder.HasIndex(look => look.OwnerUserId)
            .HasFilter("owner_user_id IS NOT NULL");
    }
}
