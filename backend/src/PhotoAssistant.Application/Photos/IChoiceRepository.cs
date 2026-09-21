using PhotoAssistant.Domain.Entities;

namespace PhotoAssistant.Application.Photos;

/// <summary>Appending to the choice log.</summary>
public interface IChoiceRepository
{
    Task AddAsync(Choice choice, CancellationToken cancellationToken);
}
