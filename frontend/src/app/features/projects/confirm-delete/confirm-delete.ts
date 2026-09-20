import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { A11yModule } from '@angular/cdk/a11y';
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';

/** What the dialog has to say to be about a particular project. */
export interface ConfirmDeleteData {
  readonly name: string;
}

/**
 * Asking before a project is deleted.
 *
 * <p>Through the CDK's `Dialog` rather than a div with a backdrop, which is
 * what ADR-26 keeps the CDK around for: the focus trap, the return of focus to
 * whatever opened it, Escape, the `aria-modal` role and the inert background
 * are behaviour with no appearance attached. Written by hand under a deadline
 * they would be written badly, and the parts that would be dropped first are
 * exactly the ones nobody notices missing until they cannot use the screen.</p>
 */
@Component({
  selector: 'app-confirm-delete',
  imports: [A11yModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './confirm-delete.html',
  styleUrl: './confirm-delete.scss',
  host: {
    role: 'alertdialog',
    'aria-labelledby': 'confirm-delete-title',
  },
})
export class ConfirmDelete {
  protected readonly data = inject<ConfirmDeleteData>(DIALOG_DATA);

  private readonly dialog = inject<DialogRef<boolean>>(DialogRef);

  protected confirm(): void {
    this.dialog.close(true);
  }

  /**
   * Closes with a no rather than with nothing. Escape and a click on the
   * backdrop close with undefined, which reads the same way — but saying it
   * here means the caller has one shape to handle instead of two.
   */
  protected cancel(): void {
    this.dialog.close(false);
  }
}
