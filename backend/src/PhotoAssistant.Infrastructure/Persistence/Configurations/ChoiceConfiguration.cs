using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using PhotoAssistant.Domain.Entities;

namespace PhotoAssistant.Infrastructure.Persistence.Configurations;

internal sealed class ChoiceConfiguration : IEntityTypeConfiguration<Choice>
{
    public void Configure(EntityTypeBuilder<Choice> builder)
    {
        builder.HasKey(choice => choice.Id);

        builder.HasOne(choice => choice.Photo)
            .WithMany()
            .HasForeignKey(choice => choice.PhotoId)
            .OnDelete(DeleteBehavior.Restrict);

        builder.Property(choice => choice.ShownSuggestions)
            .HasColumnType("jsonb")
            .IsRequired();

        builder.Property(choice => choice.Outcome)
            .HasConversion<string>()
            .HasMaxLength(32)
            .IsRequired();

        builder.Property(choice => choice.FinalEdit).HasColumnType("jsonb");

        builder.Property(choice => choice.CreatedAt)
            .HasDefaultValueSql("now()")
            .IsRequired();

        // Acceptance rate is counted per photo and per outcome when the logs
        // start feeding back into ranking.
        builder.HasIndex(choice => new { choice.PhotoId, choice.Outcome });
        builder.HasIndex(choice => choice.UserId);
    }
}
