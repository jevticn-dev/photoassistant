using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using PhotoAssistant.Domain.Entities;
using Pgvector;

namespace PhotoAssistant.Infrastructure.Persistence.Configurations;

internal sealed class PhotoConfiguration : IEntityTypeConfiguration<Photo>
{
    public void Configure(EntityTypeBuilder<Photo> builder)
    {
        builder.HasKey(photo => photo.Id);

        // Enums are stored as text rather than as integers: the values stay
        // readable in psql and a reordered enum cannot silently reinterpret
        // existing rows.
        builder.Property(photo => photo.Source)
            .HasConversion<string>()
            .HasMaxLength(32)
            .IsRequired();

        builder.Property(photo => photo.OriginalKey).HasMaxLength(512);
        // The snake_case convention does not separate trailing digits from the
        // next word, so Pre512Key would become "pre512key". Named explicitly.
        builder.Property(photo => photo.Pre512Key).HasColumnName("pre512_key").HasMaxLength(512);
        builder.Property(photo => photo.Proxy2048Key).HasColumnName("proxy2048_key").HasMaxLength(512);
        builder.Property(photo => photo.SourceReference).HasMaxLength(64);

        // Declared as a shadow property: the column exists and migrations create
        // it, but no CLR property is exposed. Keeps Pgvector — which depends on
        // the Npgsql driver — out of the Domain project, and reflects who
        // actually owns the data: the pipeline writes it, the ML service queries
        // it. CLIP ViT-B/32 produces 512 dimensions, so this one is known now.
        builder.Property<Vector?>("ClipEmbedding").HasColumnType("vector(512)");

        builder.Property(photo => photo.Tags).HasColumnType("jsonb");

        builder.Property(photo => photo.CreatedAt)
            .HasDefaultValueSql("now()")
            .IsRequired();

        // The pipeline looks photos up by their dataset identifier to decide
        // what it has already ingested.
        builder.HasIndex(photo => new { photo.Source, photo.SourceReference })
            .IsUnique()
            .HasFilter("source_reference IS NOT NULL");

        // The search path from plan §7: "which photographs in the corpus are
        // most like the one the user just uploaded". That is a nearest-neighbour
        // query over every row on every request, which is exactly what an
        // approximate index is for — as opposed to the style fingerprint, which
        // is only ever compared across a few dozen candidates and therefore has
        // none.
        //
        // Cosine, matching how the vectors are written: the pipeline
        // L2-normalises every CLIP embedding, and on unit-length vectors cosine
        // and Euclidean rank identically. Building the index for one measure and
        // querying with the other returns wrong neighbours and reports nothing,
        // since both are valid queries — normalising removes the possibility
        // rather than relying on everyone remembering.
        //
        // Created in a migration of its own so that it is applied **after** the
        // pipeline has filled the column. Built over an empty table it would
        // still be correct, but every row inserted afterwards pays to maintain
        // an index that then has to be rebuilt to be any good.
        builder.HasIndex("ClipEmbedding")
            .HasMethod("hnsw")
            .HasOperators("vector_cosine_ops");
    }
}
