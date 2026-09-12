using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace PhotoAssistant.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class ClipEmbeddingIndex : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateIndex(
                name: "ix_photos_clip_embedding",
                table: "photos",
                column: "clip_embedding")
                .Annotation("Npgsql:IndexMethod", "hnsw")
                .Annotation("Npgsql:IndexOperators", new[] { "vector_cosine_ops" });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "ix_photos_clip_embedding",
                table: "photos");
        }
    }
}
