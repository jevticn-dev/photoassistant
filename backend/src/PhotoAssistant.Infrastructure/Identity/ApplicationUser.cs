using Microsoft.AspNetCore.Identity;

namespace PhotoAssistant.Infrastructure.Identity;

/// <summary>
/// Account record, backed by ASP.NET Core Identity.
///
/// Lives in Infrastructure on purpose: Identity is a framework concern, and
/// putting it in Domain would drag ASP.NET into the innermost layer. Domain
/// entities therefore reference their owner by a plain <c>Guid UserId</c>
/// instead of holding a navigation property to this type.
/// </summary>
public class ApplicationUser : IdentityUser<Guid>
{
    public DateTimeOffset CreatedAt { get; set; }
}
