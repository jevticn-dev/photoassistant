namespace PhotoAssistant.Domain.Enums;

/// <summary>Where a named, transferable style came from.</summary>
public enum LookSource
{
    /// <summary>Scraped or bundled preset collection (adapter 2, conditional — ADR-9).</summary>
    PresetCollection,

    /// <summary>Imported by a user from their own .xmp file (ADR-13); private by default.</summary>
    UserImported,

    /// <summary>Explicitly shared by the user who owns it.</summary>
    UserShared,
}
