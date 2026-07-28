namespace PhotoAssistant.Domain.Entities;

/// <summary>
/// A user working on one photograph. Holds the edit history; the photograph
/// itself is shared and immutable.
/// </summary>
public class Project
{
    public Guid Id { get; set; }

    /// <summary>
    /// Owner. Kept as a plain identifier rather than a navigation property so
    /// that Domain stays free of the Identity types, which live in Infrastructure.
    /// </summary>
    public Guid UserId { get; set; }

    public Guid PhotoId { get; set; }
    public Photo Photo { get; set; } = null!;

    public string Name { get; set; } = string.Empty;

    public DateTimeOffset CreatedAt { get; set; }

    public ICollection<EditVersion> Versions { get; set; } = [];
}
