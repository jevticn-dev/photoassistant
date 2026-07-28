using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using PhotoAssistant.Domain.Entities;
using Pgvector;

namespace PhotoAssistant.Infrastructure.Persistence.Configurations;

internal sealed class ExampleConfiguration : IEntityTypeConfiguration<Example>
{
    public void Configure(EntityTypeBuilder<Example> builder)
    {
        builder.HasKey(example => example.Id);

        builder.HasOne(example => example.Photo)
            .WithMany(photo => photo.Examples)
            .HasForeignKey(example => example.PhotoId)
            .OnDelete(DeleteBehavior.Cascade);

        builder.HasOne(example => example.Look)
            .WithMany()
            .HasForeignKey(example => example.LookId)
            .OnDelete(DeleteBehavior.SetNull);

        builder.Property(example => example.Edit)
            .HasColumnType("jsonb")
            .IsRequired();

        builder.Property(example => example.Expert).HasMaxLength(1);
        builder.Property(example => example.AfterKey).HasMaxLength(512);

        // Shadow property, as in PhotoConfiguration.
        // TODO (phase 2): fix the dimension once the fingerprint composition is
        // settled (colour statistics combined with DINOv2), then add the HNSW
        // index. pgvector allows an unconstrained `vector` column as long as it
        // is not indexed, which is exactly the state we want until then.
        builder.Property<Vector?>("StyleFingerprint").HasColumnType("vector");

        builder.Property(example => example.CreatedAt)
            .HasDefaultValueSql("now()")
            .IsRequired();

        // The evaluation reports the distribution of the fitting residual, and
        // the recommender filters poorly fitted examples out of the pool.
        builder.HasIndex(example => example.FitError);
        builder.HasIndex(example => example.PhotoId);
    }
}
