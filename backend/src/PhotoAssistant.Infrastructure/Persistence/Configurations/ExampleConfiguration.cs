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
        builder.Property(example => example.ExcludedReason).HasMaxLength(32);

        // Shadow property, as in PhotoConfiguration.
        //
        // The dimension is fixed in phase 2: thirteen numbers of the fitted
        // recipe followed by seventeen colour statistics, which is the plain
        // composition — no neural model. The remaining candidates are an
        // ablation axis for phase 3, and recomputing the column is minutes, so
        // this fixes a dimension without settling that question.
        //
        // Deliberately **not** indexed. The fingerprint answers "how far apart
        // are these two" over a few dozen already-retrieved candidates, where
        // every distance is computed anyway; an approximate-nearest-neighbour
        // index speeds up finding among many, not comparing among few. The
        // index that does earn its keep is on photos.clip_embedding.
        builder.Property<Vector?>("StyleFingerprint").HasColumnType("vector(30)");

        builder.Property(example => example.CreatedAt)
            .HasDefaultValueSql("now()")
            .IsRequired();

        // The evaluation reports the distribution of the fitting residual, and
        // the recommender filters poorly fitted examples out of the pool.
        builder.HasIndex(example => example.FitError);
        builder.HasIndex(example => example.PhotoId);

        // One expert edited a given photograph exactly once, so a second row for
        // the same pair is a duplicate rather than new evidence.
        //
        // Until phase 2 the only thing preventing one was the pipeline manifest,
        // which skips work already done. That holds only as long as every writer
        // remembers to go through it, and phase 2 adds two more writers — the
        // fingerprint pass and publish. The manifest still prevents the *work*
        // from being repeated; this prevents the *damage* if it is. It is also
        // what makes ON CONFLICT possible, so a restart updates a row instead of
        // adding one beside it.
        //
        // Filtered because user uploads have no expert, and several nulls in a
        // column are not "the same value" for a unique index in Postgres anyway —
        // the filter states the intent rather than relying on that.
        builder.HasIndex(example => new { example.PhotoId, example.Expert })
            .IsUnique()
            .HasFilter("expert IS NOT NULL");
    }
}
