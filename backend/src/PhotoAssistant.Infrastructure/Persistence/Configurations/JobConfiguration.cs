using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using PhotoAssistant.Domain.Entities;

namespace PhotoAssistant.Infrastructure.Persistence.Configurations;

internal sealed class JobConfiguration : IEntityTypeConfiguration<Job>
{
    public void Configure(EntityTypeBuilder<Job> builder)
    {
        builder.HasKey(job => job.Id);

        builder.Property(job => job.Type)
            .HasConversion<string>()
            .HasMaxLength(32)
            .IsRequired();

        builder.Property(job => job.Status)
            .HasConversion<string>()
            .HasMaxLength(32)
            .IsRequired();

        builder.Property(job => job.Payload)
            .HasColumnType("jsonb")
            .IsRequired();

        builder.Property(job => job.Result).HasColumnType("jsonb");

        builder.Property(job => job.CreatedAt)
            .HasDefaultValueSql("now()")
            .IsRequired();

        builder.Property(job => job.UpdatedAt)
            .HasDefaultValueSql("now()")
            .IsRequired();

        // The worker polls for the oldest pending job of a given type.
        builder.HasIndex(job => new { job.Status, job.Type, job.CreatedAt });
    }
}
