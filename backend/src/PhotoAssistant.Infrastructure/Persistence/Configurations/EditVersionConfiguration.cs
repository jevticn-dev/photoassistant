using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using PhotoAssistant.Domain.Entities;

namespace PhotoAssistant.Infrastructure.Persistence.Configurations;

internal sealed class EditVersionConfiguration : IEntityTypeConfiguration<EditVersion>
{
    public void Configure(EntityTypeBuilder<EditVersion> builder)
    {
        builder.HasKey(version => version.Id);

        builder.HasOne(version => version.Project)
            .WithMany(project => project.Versions)
            .HasForeignKey(version => version.ProjectId)
            .OnDelete(DeleteBehavior.Cascade);

        builder.Property(version => version.Edit)
            .HasColumnType("jsonb")
            .IsRequired();

        builder.Property(version => version.CreatedAt)
            .HasDefaultValueSql("now()")
            .IsRequired();

        // History is always read newest-first for one project.
        builder.HasIndex(version => new { version.ProjectId, version.CreatedAt });
    }
}
