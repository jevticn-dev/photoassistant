using Microsoft.EntityFrameworkCore.Migrations;
using Pgvector;

#nullable disable

namespace PhotoAssistant.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class FixFingerprintDimension : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AlterColumn<Vector>(
                name: "style_fingerprint",
                table: "looks",
                type: "vector(30)",
                nullable: true,
                oldClrType: typeof(Vector),
                oldType: "vector",
                oldNullable: true);

            migrationBuilder.AlterColumn<Vector>(
                name: "style_fingerprint",
                table: "examples",
                type: "vector(30)",
                nullable: true,
                oldClrType: typeof(Vector),
                oldType: "vector",
                oldNullable: true);

            migrationBuilder.AlterColumn<double>(
                name: "fit_error",
                table: "examples",
                type: "double precision",
                nullable: true,
                oldClrType: typeof(double),
                oldType: "double precision");

            migrationBuilder.AddColumn<string>(
                name: "excluded_reason",
                table: "examples",
                type: "character varying(32)",
                maxLength: 32,
                nullable: true);

            migrationBuilder.CreateIndex(
                name: "ix_examples_photo_id_expert",
                table: "examples",
                columns: new[] { "photo_id", "expert" },
                unique: true,
                filter: "expert IS NOT NULL");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "ix_examples_photo_id_expert",
                table: "examples");

            migrationBuilder.DropColumn(
                name: "excluded_reason",
                table: "examples");

            migrationBuilder.AlterColumn<Vector>(
                name: "style_fingerprint",
                table: "looks",
                type: "vector",
                nullable: true,
                oldClrType: typeof(Vector),
                oldType: "vector(30)",
                oldNullable: true);

            migrationBuilder.AlterColumn<Vector>(
                name: "style_fingerprint",
                table: "examples",
                type: "vector",
                nullable: true,
                oldClrType: typeof(Vector),
                oldType: "vector(30)",
                oldNullable: true);

            migrationBuilder.AlterColumn<double>(
                name: "fit_error",
                table: "examples",
                type: "double precision",
                nullable: false,
                defaultValue: 0.0,
                oldClrType: typeof(double),
                oldType: "double precision",
                oldNullable: true);
        }
    }
}
