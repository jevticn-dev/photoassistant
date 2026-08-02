using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using PhotoAssistant.Domain.Entities;

namespace PhotoAssistant.Infrastructure.Persistence.Configurations;

internal sealed class ProjectConfiguration : IEntityTypeConfiguration<Project>
{
    public void Configure(EntityTypeBuilder<Project> builder)
    {
        builder.HasKey(project => project.Id);

        builder.Property(project => project.Name).HasMaxLength(200).IsRequired();

        builder.HasOne(project => project.Photo)
            .WithMany()
            .HasForeignKey(project => project.PhotoId)
            .OnDelete(DeleteBehavior.Restrict);

        // Foreign key to the Identity table declared by column rather than by
        // navigation property, so that Domain stays free of Identity types.
        builder.HasIndex(project => project.UserId);

        builder.Property(project => project.CreatedAt)
            .HasDefaultValueSql("now()")
            .IsRequired();
    }
}
