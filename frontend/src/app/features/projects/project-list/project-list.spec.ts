import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Observable, of } from 'rxjs';
import { vi } from 'vitest';

import { environment } from '../../../../environments/environment';
import { provideTranslations } from '../../../core/i18n/translation.config';
import { type ProjectListItem } from '../projects-service';
import { ProjectList } from './project-list';

const PROJECTS: ProjectListItem[] = [
  {
    id: '0199a1f0-0000-7000-8000-000000000001',
    name: 'Alpine Ridge',
    photoId: '0199a1f0-0000-7000-8000-00000000000a',
    versionCount: 3,
    lastEditedAt: '2026-09-19T10:00:00+00:00',
  },
  {
    id: '0199a1f0-0000-7000-8000-000000000002',
    name: 'Pine Valley',
    photoId: '0199a1f0-0000-7000-8000-00000000000b',
    versionCount: 0,
    lastEditedAt: '2026-09-18T10:00:00+00:00',
  },
];

describe('ProjectList', () => {
  let fixture: ComponentFixture<ProjectList>;
  let http: HttpTestingController;

  /** What the confirmation answers. Undefined is Escape or a click outside. */
  let answer: boolean | undefined;

  beforeEach(() => {
    answer = true;

    // The thumbnails fetch bytes and make object URLs; jsdom has neither, and
    // what they do is tested where they live.
    URL.createObjectURL = vi.fn(() => 'blob:stub');
    URL.revokeObjectURL = vi.fn();
  });

  async function open(projects: ProjectListItem[] = PROJECTS): Promise<void> {
    await TestBed.configureTestingModule({
      imports: [ProjectList],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        provideTranslations(),
        {
          // The dialog itself is the CDK's; what is worth testing here is that
          // nothing is deleted until it answers yes.
          provide: Dialog,
          useValue: {
            open: (): { closed: Observable<boolean | undefined> } => ({ closed: of(answer) }),
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ProjectList);
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    http.expectOne(`${environment.apiBaseUrl}/projects`).flush(projects);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  afterEach(() => {
    http?.match((request) => request.url.includes('/i18n/')).forEach((r) => r.flush({}));
    http
      ?.match((request) => request.url.includes('/thumbnail'))
      .forEach((r) => r.flush(new Blob()));
    http?.verify();
    TestBed.resetTestingModule();
  });

  function element(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function cards(): HTMLElement[] {
    return [...element().querySelectorAll<HTMLElement>('.card')];
  }

  function button(card: HTMLElement, label: string): HTMLButtonElement {
    return [...card.querySelectorAll('button')].find(
      (candidate) => candidate.textContent?.trim() === label,
    )!;
  }

  it('lists what came back, one card each', async () => {
    await open();

    expect(cards()).toHaveLength(2);
    expect(cards()[0].textContent).toContain('Alpine Ridge');
  });

  it('says a project has nothing saved rather than showing it as empty', async () => {
    // A project made by an upload and then left is an ordinary row, not a
    // fault: the upload is what creates it (decision G).
    await open();

    expect(cards()[1].textContent).toContain('projects.versions.none');
    expect(cards()[0].textContent).toContain('projects.versions.many');
  });

  it('offers a way to start rather than an empty list', async () => {
    // A heading with nothing under it reads as something that failed to load.
    await open([]);

    expect(element().querySelector('.empty')).not.toBeNull();
    expect(element().querySelectorAll('.card')).toHaveLength(0);
  });

  it('a card opens the project, which is not the same as opening the editor', async () => {
    // An abandoned upload has never been past the three suggestions, and that
    // is where opening it belongs. chosenGuard sends on the ones that have.
    await open();

    const link = cards()[0].querySelector('.card__name');

    expect(link?.getAttribute('href')).toBe(`/projects/${PROJECTS[0].id}`);
  });

  it('renaming patches the row it changed and nothing else', async () => {
    await open();

    button(cards()[0], 'projects.rename.short').click();
    fixture.detectChanges();

    const field = element().querySelector<HTMLInputElement>('.rename__field')!;
    field.value = 'Alpine Ridge, colder';
    element().querySelector('form')!.dispatchEvent(new Event('submit'));

    http
      .expectOne(`${environment.apiBaseUrl}/projects/${PROJECTS[0].id}`)
      .flush({ name: 'Alpine Ridge, colder' });
    fixture.detectChanges();

    expect(cards()[0].textContent).toContain('Alpine Ridge, colder');
    expect(cards()[1].textContent).toContain('Pine Valley');
  });

  it('a rename that changes nothing asks the server nothing', async () => {
    await open();

    button(cards()[0], 'projects.rename.short').click();
    fixture.detectChanges();

    element().querySelector('form')!.dispatchEvent(new Event('submit'));
    fixture.detectChanges();

    // No expectOne: the verify in afterEach is what fails if a request was made.
    expect(element().querySelector('.rename__field')).toBeNull();
  });

  it('deleting asks first, and a no deletes nothing', async () => {
    answer = false;
    await open();

    button(cards()[0], 'projects.delete.short').click();
    fixture.detectChanges();

    expect(cards()).toHaveLength(2);
  });

  it('a yes removes the row without reloading the list', async () => {
    await open();

    button(cards()[0], 'projects.delete.short').click();
    http.expectOne(`${environment.apiBaseUrl}/projects/${PROJECTS[0].id}`).flush(null);
    fixture.detectChanges();

    expect(cards()).toHaveLength(1);
    expect(element().textContent).not.toContain('Alpine Ridge');
  });
});
