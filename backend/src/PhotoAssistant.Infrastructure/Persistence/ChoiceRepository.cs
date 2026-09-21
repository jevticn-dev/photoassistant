using PhotoAssistant.Application.Photos;
using PhotoAssistant.Domain.Entities;

namespace PhotoAssistant.Infrastructure.Persistence;

internal sealed class ChoiceRepository(PhotoAssistantDbContext context) : IChoiceRepository
{
    public async Task AddAsync(Choice choice, CancellationToken cancellationToken)
    {
        context.Choices.Add(choice);

        await context.SaveChangesAsync(cancellationToken);
    }
}
