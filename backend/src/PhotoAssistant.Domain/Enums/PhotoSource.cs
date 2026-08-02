namespace PhotoAssistant.Domain.Enums;

/// <summary>Where a photo entered the system from.</summary>
public enum PhotoSource
{
    /// <summary>Ingested from the MIT-Adobe FiveK dataset by the offline pipeline.</summary>
    Fivek,

    /// <summary>Uploaded by a user.</summary>
    User,
}
