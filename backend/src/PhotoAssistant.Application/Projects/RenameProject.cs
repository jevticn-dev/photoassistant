namespace PhotoAssistant.Application.Projects;

/// <summary>The longest name the column holds (ProjectConfiguration).</summary>
public static class ProjectName
{
    public const int MaxLength = 200;

    /// <summary>
    /// Trims and refuses what cannot be a name.
    ///
    /// <para>
    /// Whitespace is trimmed rather than rejected: a trailing space is a typing
    /// accident, not an intention worth an error message. What is left must be
    /// something, because a project with a blank name cannot be told apart from
    /// its neighbours in a list.
    /// </para>
    /// </summary>
    public static string? Clean(string? value)
    {
        var trimmed = value?.Trim();

        return string.IsNullOrEmpty(trimmed) || trimmed.Length > MaxLength ? null : trimmed;
    }
}

public sealed record RenameProjectResult
{
    private RenameProjectResult()
    {
    }

    public bool Succeeded { get; private init; }

    public bool NotFound { get; private init; }

    public string? Error { get; private init; }

    public string? Name { get; private init; }

    public static RenameProjectResult Success(string name) =>
        new() { Succeeded = true, Name = name };

    public static RenameProjectResult Missing() => new() { NotFound = true };

    public static RenameProjectResult Invalid(string error) => new() { Error = error };
}

/// <summary>
/// Renaming a project. The only thing about a project that is editable: the
/// photograph is what it is, and the edits are versions.
/// </summary>
public sealed class RenameProjectHandler(IProjectRepository projects)
{
    public async Task<RenameProjectResult> RenameAsync(
        Guid projectId,
        Guid userId,
        string? name,
        CancellationToken cancellationToken)
    {
        var cleaned = ProjectName.Clean(name);

        if (cleaned is null)
        {
            return RenameProjectResult.Invalid(
                $"A name is required, and may be at most {ProjectName.MaxLength} characters.");
        }

        var renamed = await projects.RenameForUserAsync(
            projectId, userId, cleaned, cancellationToken);

        return renamed
            ? RenameProjectResult.Success(cleaned)
            : RenameProjectResult.Missing();
    }
}
