// File list for iPhone and iPad: a recycled collection view (list or grid) with thumbnails,
// a context menu, swipe actions and a selection bar. Included inside SooveeViewController.
#if !TARGET_OS_TV

static NSSet *ThumbnailTypes(void) {
    static NSSet *types;static dispatch_once_t once;
    dispatch_once(&once,^{types=[NSSet setWithArray:@[@"jpg",@"jpeg",@"png",@"heic",@"heif",@"gif",@"webp",@"tif",@"tiff",@"bmp",@"dng",@"mov",@"mp4",@"m4v",@"pdf",@"key",@"pages",@"numbers",@"usdz"]];});
    return types;
}
static NSDateFormatter *ShortDate(void) {
    static NSDateFormatter *formatter;static dispatch_once_t once;
    dispatch_once(&once,^{formatter=[NSDateFormatter new];formatter.dateStyle=NSDateFormatterShortStyle;formatter.timeStyle=NSDateFormatterShortStyle;formatter.doesRelativeDateFormatting=YES;});
    return formatter;
}

- (void)setupFileList:(UIStackView *)body root:(UIStackView *)root {
    self.thumbnails=[NSCache new];self.thumbnails.countLimit=800;
    self.filesContainer=[UIStackView new];self.filesContainer.axis=UILayoutConstraintAxisVertical;self.filesContainer.spacing=10;self.filesContainer.hidden=YES;
    // The header (title, path, search, tools) scrolls away with the list, leaving the screen to the files.
    self.filesHeader=[UIStackView new];self.filesHeader.axis=UILayoutConstraintAxisVertical;self.filesHeader.spacing=8;self.filesHeader.translatesAutoresizingMaskIntoConstraints=NO;
    self.filesHeader.layoutMarginsRelativeArrangement=YES;self.filesHeader.directionalLayoutMargins=NSDirectionalEdgeInsetsMake(0,0,10,0);
    self.filesCollection=[[UICollectionView alloc]initWithFrame:CGRectZero collectionViewLayout:[self fileLayout]];
    self.filesCollection.backgroundColor=UIColor.clearColor;self.filesCollection.delegate=self;self.filesCollection.keyboardDismissMode=UIScrollViewKeyboardDismissModeOnDrag;
    self.filesCollection.allowsSelection=YES;
    UIRefreshControl *refresh=[UIRefreshControl new];__weak UIRefreshControl *weakRefresh=refresh;
    [refresh addAction:[UIAction actionWithHandler:^(UIAction *a){[weakRefresh endRefreshing];[self showFiles];}] forControlEvents:UIControlEventValueChanged];self.filesCollection.refreshControl=refresh;
    __weak SooveeViewController *weakSelf=self;
    UICollectionViewCellRegistration *list=[UICollectionViewCellRegistration registrationWithCellClass:UICollectionViewListCell.class configurationHandler:^(UICollectionViewListCell *cell,NSIndexPath *indexPath,NSString *name){[weakSelf configureListCell:cell name:name];}];
    UICollectionViewCellRegistration *grid=[UICollectionViewCellRegistration registrationWithCellClass:SooveeGridCell.class configurationHandler:^(SooveeGridCell *cell,NSIndexPath *indexPath,NSString *name){[weakSelf configureGridCell:cell name:name];}];
    self.filesSource=[[UICollectionViewDiffableDataSource alloc]initWithCollectionView:self.filesCollection cellProvider:^UICollectionViewCell *(UICollectionView *view,NSIndexPath *indexPath,NSString *name){
        return weakSelf.tiles?[view dequeueConfiguredReusableCellWithRegistration:grid forIndexPath:indexPath item:name]:[view dequeueConfiguredReusableCellWithRegistration:list forIndexPath:indexPath item:name];}];
    UICollectionViewSupplementaryRegistration *header=[UICollectionViewSupplementaryRegistration registrationWithSupplementaryClass:UICollectionReusableView.class elementKind:UICollectionElementKindSectionHeader configurationHandler:^(UICollectionReusableView *view,NSString *kind,NSIndexPath *indexPath){
        UIStackView *content=weakSelf.filesHeader;if(content.superview==view)return;[content removeFromSuperview];[view addSubview:content];
        [NSLayoutConstraint activateConstraints:@[[content.leadingAnchor constraintEqualToAnchor:view.leadingAnchor],[content.trailingAnchor constraintEqualToAnchor:view.trailingAnchor],[content.topAnchor constraintEqualToAnchor:view.topAnchor],[content.bottomAnchor constraintEqualToAnchor:view.bottomAnchor]]];}];
    self.filesSource.supplementaryViewProvider=^UICollectionReusableView *(UICollectionView *view,NSString *kind,NSIndexPath *indexPath){return [view dequeueConfiguredReusableSupplementaryViewWithRegistration:header forIndexPath:indexPath];};
    [self.filesContainer addArrangedSubview:self.filesCollection];
    [body addArrangedSubview:self.filesContainer];
    // Shown instead of the tab bar while items are selected, within thumb reach.
    self.selectionBar=[UIStackView new];self.selectionBar.axis=UILayoutConstraintAxisHorizontal;self.selectionBar.distribution=UIStackViewDistributionFillEqually;self.selectionBar.hidden=YES;
    [root addArrangedSubview:self.selectionBar];
}

- (UICollectionViewLayout *)fileLayout {
    __weak SooveeViewController *weakSelf=self;
    return [[UICollectionViewCompositionalLayout alloc]initWithSectionProvider:^NSCollectionLayoutSection *(NSInteger index,id<NSCollectionLayoutEnvironment> environment){
        if(weakSelf.tiles){
            CGFloat width=environment.container.effectiveContentSize.width;NSInteger columns=MAX(2,(NSInteger)floor(width/116));
            NSCollectionLayoutSize *itemSize=[NSCollectionLayoutSize sizeWithWidthDimension:[NSCollectionLayoutDimension fractionalWidthDimension:1.0/columns] heightDimension:[NSCollectionLayoutDimension estimatedDimension:150]];
            NSCollectionLayoutItem *item=[NSCollectionLayoutItem itemWithLayoutSize:itemSize];
            NSCollectionLayoutSize *groupSize=[NSCollectionLayoutSize sizeWithWidthDimension:[NSCollectionLayoutDimension fractionalWidthDimension:1] heightDimension:[NSCollectionLayoutDimension estimatedDimension:150]];
            NSCollectionLayoutGroup *group=[NSCollectionLayoutGroup horizontalGroupWithLayoutSize:groupSize repeatingSubitem:item count:columns];group.interItemSpacing=[NSCollectionLayoutSpacing fixedSpacing:8];
            NSCollectionLayoutSection *section=[NSCollectionLayoutSection sectionWithGroup:group];section.interGroupSpacing=8;section.contentInsets=NSDirectionalEdgeInsetsMake(0,0,24,0);
            NSCollectionLayoutBoundarySupplementaryItem *header=[NSCollectionLayoutBoundarySupplementaryItem boundarySupplementaryItemWithLayoutSize:[NSCollectionLayoutSize sizeWithWidthDimension:[NSCollectionLayoutDimension fractionalWidthDimension:1] heightDimension:[NSCollectionLayoutDimension estimatedDimension:160]] elementKind:UICollectionElementKindSectionHeader alignment:NSRectAlignmentTop];
            section.boundarySupplementaryItems=@[header];
            return section;}
        UICollectionLayoutListConfiguration *config=[[UICollectionLayoutListConfiguration alloc]initWithAppearance:UICollectionLayoutListAppearanceInsetGrouped];
        config.backgroundColor=UIColor.clearColor;config.headerMode=UICollectionLayoutListHeaderModeSupplementary;config.headerTopPadding=0;
        config.trailingSwipeActionsConfigurationProvider=^UISwipeActionsConfiguration *(NSIndexPath *indexPath){return [weakSelf trailingSwipe:indexPath];};
        config.leadingSwipeActionsConfigurationProvider=^UISwipeActionsConfiguration *(NSIndexPath *indexPath){return [weakSelf leadingSwipe:indexPath];};
        NSCollectionLayoutSection *section=[NSCollectionLayoutSection sectionWithListConfiguration:config layoutEnvironment:environment];
        section.contentInsetsReference=UIContentInsetsReferenceNone;section.contentInsets=NSDirectionalEdgeInsetsMake(0,0,24,0);
        return section;}];
}

#pragma mark Data

- (void)showFilesLoading {
    [self clear:@"files"];[self buildFilesHeader];
    self.entryByName=@{};NSDiffableDataSourceSnapshot *empty=[NSDiffableDataSourceSnapshot new];[empty appendSectionsWithIdentifiers:@[@"files"]];[self.filesSource applySnapshotUsingReloadData:empty];
    UIActivityIndicatorView *spinner=[[UIActivityIndicatorView alloc]initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleLarge];[spinner startAnimating];
    self.filesCollection.backgroundView=spinner;
}
- (NSArray *)visibleFileEntries {
    NSMutableArray *entries=[NSMutableArray new];NSArray *source=self.fileEntries;
    if([self.path isEqual:@"/"]&&!self.peer.length&&!self.searchQuery)source=[source arrayByAddingObjectsFromArray:[self unavailableLocations]];
    for(NSDictionary *item in source)if(!self.filter.length||[item[@"name"] localizedCaseInsensitiveContainsString:self.filter])[entries addObject:item];
    NSInteger order=self.sortOrder;
    [entries sortUsingComparator:^NSComparisonResult(NSDictionary *a,NSDictionary *b){BOOL ad=[a[@"directory"] boolValue],bd=[b[@"directory"] boolValue];if(ad!=bd)return ad?NSOrderedAscending:NSOrderedDescending;
        if(order){NSString *key=order==1?@"modified":@"bytes";NSComparisonResult result=[b[key]?:@0 compare:a[key]?:@0];if(result!=NSOrderedSame)return result;}
        return [a[@"name"] localizedStandardCompare:b[@"name"]];}];
    return entries;
}
- (void)renderFiles {
    [self clear:@"files"];[self buildFilesHeader];[self applyFiles];
}
// Data only: keeps the header (and the search field's focus) as it is.
- (void)applyFiles {
    NSArray *entries=[self visibleFileEntries];NSMutableDictionary *byName=[NSMutableDictionary dictionaryWithCapacity:entries.count];NSMutableArray *names=[NSMutableArray arrayWithCapacity:entries.count];
    for(NSDictionary *item in entries){NSString *name=item[@"name"];if(![name isKindOfClass:NSString.class]||byName[name])continue;byName[name]=item;[names addObject:name];}
    self.entryByName=byName;
    for(NSString *name in self.selection.allObjects)if(!byName[name])[self.selection removeObject:name];
    [self updateFileCount];[self.filesCollection.collectionViewLayout invalidateLayout];
    NSDiffableDataSourceSnapshot *snapshot=[NSDiffableDataSourceSnapshot new];[snapshot appendSectionsWithIdentifiers:@[@"files"]];[snapshot appendItemsWithIdentifiers:names];
    [self.filesSource applySnapshotUsingReloadData:snapshot];
    if(names.count)self.filesCollection.backgroundView=nil;
    else{UILabel *empty=[self textLabel:T(self.filter.length?@"No matching files.":@"This folder is empty.") style:UIFontTextStyleBody weight:UIFontWeightRegular color:UIColor.secondaryLabelColor];empty.textAlignment=NSTextAlignmentCenter;self.filesCollection.backgroundView=empty;}
    [self updateFileCount];[self updateSelectionUI];
}
- (void)updateFileCount {
    NSUInteger count=self.entryByName.count;
    if(self.filter.length&&!self.searchQuery&&!self.peer.length&&![self.path isEqual:@"/"]&&!self.selection.count){self.filesCount.text=[NSString stringWithFormat:@"%@ · %@",[self itemCount:count],T(@"Return searches subfolders too")];return;}
    if(self.searchQuery&&!self.selection.count){self.filesCount.text=[NSString stringWithFormat:@"%@ · %@",[self itemCount:count],T(self.searchComplete?@"in all subfolders":@"first results only")];return;}
    self.filesCount.text=self.selection.count?[NSString stringWithFormat:@"%@ · %lu %@",[self itemCount:count],(unsigned long)self.selection.count,T(@"selected")]:[self itemCount:count];
}

#pragma mark Header

- (UIButton *)headerTool:(NSString *)symbol label:(NSString *)label menu:(UIMenu *)menu action:(dispatch_block_t)action {
    UIButton *button=[UIButton buttonWithType:UIButtonTypeSystem];UIButtonConfiguration *cfg=[UIButtonConfiguration tintedButtonConfiguration];
    cfg.image=[UIImage systemImageNamed:symbol];cfg.baseForegroundColor=Accent();cfg.baseBackgroundColor=Accent();cfg.cornerStyle=UIButtonConfigurationCornerStyleMedium;
    cfg.preferredSymbolConfigurationForImage=[UIImageSymbolConfiguration configurationWithTextStyle:UIFontTextStyleBody scale:UIImageSymbolScaleMedium];
    button.configuration=cfg;button.accessibilityLabel=label;button.toolTip=label;
    [button.widthAnchor constraintEqualToConstant:44].active=YES;[button.heightAnchor constraintEqualToConstant:40].active=YES;
    if(menu){button.menu=menu;button.showsMenuAsPrimaryAction=YES;}
    else [button addAction:[UIAction actionWithHandler:^(UIAction *a){action();}] forControlEvents:UIControlEventPrimaryActionTriggered];
    return button;
}
- (void)buildFilesHeader {
    for(UIView *view in self.filesHeader.arrangedSubviews){[self.filesHeader removeArrangedSubview:view];[view removeFromSuperview];}
    NSString *path=self.path;BOOL root=[path isEqual:@"/"];
    NSString *device=T(@"This device");for(NSDictionary *peer in self.state[@"peers"])if([peer[@"id"] isEqual:self.peer])device=peer[@"name"];
    if(self.searchQuery){
        UIButton *button=[UIButton buttonWithType:UIButtonTypeSystem];UIButtonConfiguration *cfg=[UIButtonConfiguration plainButtonConfiguration];
        cfg.title=path.lastPathComponent;cfg.image=[UIImage systemImageNamed:@"chevron.backward"];cfg.imagePadding=4;cfg.baseForegroundColor=Accent();cfg.contentInsets=NSDirectionalEdgeInsetsMake(6,0,6,12);button.configuration=cfg;
        [button addAction:[UIAction actionWithHandler:^(UIAction *a){self.searchQuery=nil;self.filter=@"";[self showFiles];}] forControlEvents:UIControlEventPrimaryActionTriggered];
        [self.filesHeader addArrangedSubview:[[UIStackView alloc]initWithArrangedSubviews:@[button,[UIView new]]]];
    }
    else if(!root){
        NSString *parent=path.stringByDeletingLastPathComponent;NSString *back=[parent isEqual:@"/"]?(self.peer.length?device:T(@"Files")):parent.lastPathComponent;
        UIButton *button=[UIButton buttonWithType:UIButtonTypeSystem];UIButtonConfiguration *cfg=[UIButtonConfiguration plainButtonConfiguration];
        cfg.title=back;cfg.image=[UIImage systemImageNamed:@"chevron.backward"];cfg.imagePadding=4;cfg.baseForegroundColor=Accent();cfg.contentInsets=NSDirectionalEdgeInsetsMake(6,0,6,12);
        cfg.preferredSymbolConfigurationForImage=[UIImageSymbolConfiguration configurationWithTextStyle:UIFontTextStyleBody scale:UIImageSymbolScaleMedium];button.configuration=cfg;
        [button addAction:[UIAction actionWithHandler:^(UIAction *a){[self openFolder:parent];}] forControlEvents:UIControlEventPrimaryActionTriggered];
        UIStackView *bar=[[UIStackView alloc]initWithArrangedSubviews:@[button,[UIView new]]];[self.filesHeader addArrangedSubview:bar];
    }
    UILabel *title=[self textLabel:self.searchQuery?[NSString stringWithFormat:@"„%@“",self.searchQuery]:root?(self.peer.length?device:T(@"Files")):path.lastPathComponent style:UIFontTextStyleLargeTitle weight:UIFontWeightBold color:UIColor.labelColor];
    title.numberOfLines=1;title.adjustsFontSizeToFitWidth=YES;title.minimumScaleFactor=.6;title.accessibilityTraits=UIAccessibilityTraitHeader;[self.filesHeader addArrangedSubview:title];
    if(!root||self.peer.length){UILabel *where=[self textLabel:[NSString stringWithFormat:@"%@ · %@",device,path] style:UIFontTextStyleFootnote weight:UIFontWeightRegular color:UIColor.secondaryLabelColor];where.numberOfLines=1;where.lineBreakMode=NSLineBreakByTruncatingHead;[self.filesHeader addArrangedSubview:where];}
    // Search field filters live; sort, view and more sit next to it.
    UISearchTextField *search=[UISearchTextField new];search.placeholder=T(self.searchQuery?@"Filter results":@"Filter or search");search.text=self.filter;search.returnKeyType=self.peer.length||root||self.searchQuery?UIReturnKeyDone:UIReturnKeySearch;search.autocorrectionType=UITextAutocorrectionTypeNo;
    [search addAction:[UIAction actionWithHandler:^(UIAction *a){self.filter=search.text?:@"";[self applyFiles];}] forControlEvents:UIControlEventEditingChanged];
    [search addAction:[UIAction actionWithHandler:^(UIAction *a){[search resignFirstResponder];
        // Return searches this folder and all its subfolders (local storage).
        if(!self.peer.length&&!root&&!self.searchQuery&&search.text.length)[self deepSearch:search.text];}] forControlEvents:UIControlEventEditingDidEndOnExit];
    NSArray *sortNames=@[@"Name",@"Newest first",@"Largest first"];NSMutableArray *sorts=[NSMutableArray new];
    for(NSInteger i=0;i<3;i++){NSInteger order=i;UIAction *choice=[UIAction actionWithTitle:T(sortNames[i]) image:nil identifier:nil handler:^(UIAction *a){self.sortOrder=order;[NSUserDefaults.standardUserDefaults setInteger:order forKey:@"fileSort"];[self renderFiles];}];if(i==self.sortOrder)choice.state=UIMenuElementStateOn;[sorts addObject:choice];}
    UIMenu *sort=[UIMenu menuWithTitle:T(@"Sort") children:sorts];
    UIAction *list=[UIAction actionWithTitle:T(@"List") image:[UIImage systemImageNamed:@"list.bullet"] identifier:nil handler:^(UIAction *a){self.tiles=NO;[NSUserDefaults.standardUserDefaults setBool:NO forKey:@"fileGrid"];[self renderFiles];}];
    UIAction *grid=[UIAction actionWithTitle:T(@"Grid") image:[UIImage systemImageNamed:@"square.grid.2x2"] identifier:nil handler:^(UIAction *a){self.tiles=YES;[NSUserDefaults.standardUserDefaults setBool:YES forKey:@"fileGrid"];[self renderFiles];}];
    (self.tiles?grid:list).state=UIMenuElementStateOn;
    UIMenu *view=[UIMenu menuWithTitle:@"" image:nil identifier:nil options:UIMenuOptionsDisplayInline children:@[list,grid]];
    NSMutableArray *more=[NSMutableArray new];
    if(!root)[more addObject:[UIAction actionWithTitle:T(@"New folder") image:[UIImage systemImageNamed:@"folder.badge.plus"] identifier:nil handler:^(UIAction *a){[self editItem:nil];}]];
    if(!root&&!self.peer.length)[more addObject:[UIAction actionWithTitle:T(@"New text file") image:[UIImage systemImageNamed:@"doc.badge.plus"] identifier:nil handler:^(UIAction *a){[self newTextFile];}]];
    if(self.entryByName.count||self.fileEntries.count)[more addObject:[UIAction actionWithTitle:T(@"Select") image:[UIImage systemImageNamed:@"checkmark.circle"] identifier:nil handler:^(UIAction *a){[self startSelection];}]];
    if(!root&&!self.searchQuery){BOOL favorite=[self isFavorite:path];
        [more addObject:[UIAction actionWithTitle:T(favorite?@"Remove from favorites":@"Add to favorites") image:[UIImage systemImageNamed:favorite?@"star.slash":@"star"] identifier:nil handler:^(UIAction *a){[self toggleFavorite:path name:path.lastPathComponent];[self buildFilesHeader];[self applyFiles];}]];}
    if(!self.peer.length&&!root&&!self.searchQuery)[more addObject:[UIAction actionWithTitle:T(@"Search subfolders…") image:[UIImage systemImageNamed:@"magnifyingglass"] identifier:nil handler:^(UIAction *a){[self askSearch];}]];
    if(!self.peer.length&&root)[more addObject:[UIAction actionWithTitle:T(@"Add folder from Files…") image:[UIImage systemImageNamed:@"folder.badge.person.crop"] identifier:nil handler:^(UIAction *a){[self addFolder];}]];
    [more addObject:[UIAction actionWithTitle:T(@"Refresh") image:[UIImage systemImageNamed:@"arrow.clockwise"] identifier:nil handler:^(UIAction *a){[self showFiles];}]];
    UIMenu *options=[UIMenu menuWithChildren:@[[UIMenu menuWithTitle:@"" image:nil identifier:nil options:UIMenuOptionsDisplayInline children:more],view,sort]];
    UIStackView *tools=[[UIStackView alloc]initWithArrangedSubviews:@[search,
        [self headerTool:@"arrow.up.arrow.down" label:T(@"Sort") menu:sort action:nil],
        [self headerTool:@"ellipsis" label:T(@"More") menu:options action:nil]]];
    tools.axis=UILayoutConstraintAxisHorizontal;tools.spacing=8;tools.alignment=UIStackViewAlignmentCenter;[self.filesHeader addArrangedSubview:tools];
    self.filesCount=[self textLabel:@" " style:UIFontTextStyleFootnote weight:UIFontWeightRegular color:UIColor.secondaryLabelColor];[self.filesHeader addArrangedSubview:self.filesCount];
    if(root&&!self.peer.length)self.filesCount.text=T(@"Locations");
}

#pragma mark Cells

- (NSString *)itemDetail:(NSDictionary *)item {
    if([self.path isEqual:@"/"]&&!self.peer.length){
        if([item[@"unavailable"] boolValue])return T(@"Not available now");
        if([[self locationNamed:item[@"name"]][@"network"] boolValue])return T(@"Network location");
        if([item[@"name"] isEqual:@"Shared"])return T(@"Soovee folder on this iPhone");
        if([self locationNamed:item[@"name"]])return T(@"Folder from Files");}
    BOOL directory=[item[@"directory"] boolValue];double modified=[item[@"modified"] doubleValue];
    NSString *size=directory?T(@"Folder"):[NSByteCountFormatter stringFromByteCount:[item[@"bytes"] longLongValue] countStyle:NSByteCountFormatterCountStyleFile];
    return modified>0?[NSString stringWithFormat:@"%@ · %@",size,[ShortDate() stringFromDate:[NSDate dateWithTimeIntervalSince1970:modified]]]:size;
}
- (NSString *)localPathFor:(NSDictionary *)item {
    if(self.peer.length||!self.filesBase.length)return nil;return [self.filesBase stringByAppendingPathComponent:item[@"name"]];
}
// A real preview for pictures, videos and PDFs; requested lazily for visible cells and cached.
- (UIImage *)thumbnailFor:(NSDictionary *)item size:(CGFloat)size {
    NSString *file=[self localPathFor:item];if(!file||[item[@"directory"] boolValue]||![ThumbnailTypes() containsObject:[item[@"name"] pathExtension].lowercaseString])return nil;
    NSString *key=[NSString stringWithFormat:@"%@|%@|%.0f",file,item[@"modified"]?:@0,size];id cached=[self.thumbnails objectForKey:key];
    if([cached isKindOfClass:UIImage.class])return cached;if(cached)return nil;
    [self.thumbnails setObject:NSNull.null forKey:key];NSString *name=item[@"name"],*base=self.filesBase;
    QLThumbnailGenerationRequest *request=[[QLThumbnailGenerationRequest alloc]initWithFileAtURL:[NSURL fileURLWithPath:file] size:CGSizeMake(size,size) scale:UIScreen.mainScreen.scale representationTypes:QLThumbnailGenerationRequestRepresentationTypeThumbnail];
    [QLThumbnailGenerator.sharedGenerator generateBestRepresentationForRequest:request completionHandler:^(QLThumbnailRepresentation *thumbnail,NSError *error){
        UIImage *image=thumbnail.UIImage;if(!image)return;
        dispatch_async(dispatch_get_main_queue(),^{[self.thumbnails setObject:image forKey:key];
            if(![self.filesBase isEqual:base]||!self.entryByName[name]||![self.screen isEqual:@"files"])return;
            NSDiffableDataSourceSnapshot *snapshot=self.filesSource.snapshot;if([snapshot indexOfItemIdentifier:name]==NSNotFound)return;
            [snapshot reconfigureItemsWithIdentifiers:@[name]];[self.filesSource applySnapshot:snapshot animatingDifferences:NO];});}];
    return nil;
}
- (UIImage *)symbolFor:(NSDictionary *)item {
    if([self.path isEqual:@"/"]&&!self.peer.length){NSDictionary *location=[self locationNamed:item[@"name"]];
        if([item[@"unavailable"] boolValue])return [UIImage systemImageNamed:@"externaldrive.badge.xmark"];
        if([location[@"network"] boolValue])return [UIImage systemImageNamed:@"network"];
        if([item[@"name"] isEqual:@"Shared"])return [UIImage systemImageNamed:@"iphone"];}
    return [UIImage systemImageNamed:[item[@"directory"] boolValue]&&[self.path isEqual:@"/"]&&!self.peer.length?@"externaldrive.fill":[self itemSymbol:item]];
}
- (void)configureListCell:(UICollectionViewListCell *)cell name:(NSString *)name {
    NSDictionary *item=self.entryByName[name];if(!item)return;BOOL directory=[item[@"directory"] boolValue],selected=[self.selection containsObject:name];
    UIListContentConfiguration *content=[UIListContentConfiguration subtitleCellConfiguration];
    content.text=name.lastPathComponent;content.textProperties.numberOfLines=2;content.textProperties.lineBreakMode=NSLineBreakByTruncatingMiddle;
    NSString *folder=name.stringByDeletingLastPathComponent;
    content.secondaryText=folder.length?[NSString stringWithFormat:@"%@ · %@",folder,[self itemDetail:item]]:[self itemDetail:item];content.secondaryTextProperties.color=UIColor.secondaryLabelColor;content.textToSecondaryTextVerticalPadding=3;
    UIImage *thumbnail=[self thumbnailFor:item size:80];
    content.image=thumbnail?:[self symbolFor:item];content.imageProperties.tintColor=directory?Accent():UIColor.secondaryLabelColor;
    content.imageProperties.maximumSize=CGSizeMake(40,40);content.imageProperties.reservedLayoutSize=CGSizeMake(40,40);content.imageProperties.cornerRadius=thumbnail?6:0;
    content.imageProperties.preferredSymbolConfiguration=[UIImageSymbolConfiguration configurationWithPointSize:24 weight:UIImageSymbolWeightRegular];
    cell.contentConfiguration=content;
    cell.configurationUpdateHandler=^(UICollectionViewCell *view,UICellConfigurationState *state){
        UIBackgroundConfiguration *background=[[UIBackgroundConfiguration listGroupedCellConfiguration] updatedConfigurationForState:state];
        if(!state.highlighted)background.backgroundColor=selected?[Accent() colorWithAlphaComponent:.18]:Surface();view.backgroundConfiguration=background;};
    NSMutableArray *accessories=[NSMutableArray new];
    if(self.selection.count||self.selectionMode){UIImageView *mark=[[UIImageView alloc]initWithImage:[UIImage systemImageNamed:selected?@"checkmark.circle.fill":@"circle"]];mark.tintColor=selected?Accent():UIColor.tertiaryLabelColor;
        [accessories addObject:[[UICellAccessoryCustomView alloc]initWithCustomView:mark placement:UICellAccessoryPlacementLeading]];}
    else{UIButton *more=[UIButton buttonWithType:UIButtonTypeSystem];[more setImage:[UIImage systemImageNamed:@"ellipsis.circle"] forState:UIControlStateNormal];more.tintColor=Accent();
        more.frame=CGRectMake(0,0,36,44);more.menu=[self menuForItem:item];more.showsMenuAsPrimaryAction=YES;more.accessibilityLabel=[NSString stringWithFormat:T(@"More for %@"),name];
        UICellAccessoryCustomView *custom=[[UICellAccessoryCustomView alloc]initWithCustomView:more placement:UICellAccessoryPlacementTrailing];custom.maintainsFixedSize=YES;[accessories addObject:custom];}
    if(directory)[accessories addObject:[UICellAccessoryDisclosureIndicator new]];
    cell.accessories=accessories;
    cell.accessibilityLabel=name;cell.accessibilityValue=[self itemDetail:item];cell.accessibilityTraits=selected?UIAccessibilityTraitSelected|UIAccessibilityTraitButton:UIAccessibilityTraitButton;
}
- (void)configureGridCell:(SooveeGridCell *)cell name:(NSString *)name {
    NSDictionary *item=self.entryByName[name];if(!item)return;BOOL directory=[item[@"directory"] boolValue],selected=[self.selection containsObject:name];
    UIImage *thumbnail=[self thumbnailFor:item size:160];
    if(thumbnail){cell.icon.image=thumbnail;cell.icon.contentMode=UIViewContentModeScaleAspectFill;}
    else{cell.icon.image=[[self symbolFor:item] imageWithConfiguration:[UIImageSymbolConfiguration configurationWithPointSize:44 weight:UIImageSymbolWeightRegular]];cell.icon.contentMode=UIViewContentModeCenter;cell.icon.tintColor=directory?Accent():UIColor.secondaryLabelColor;}
    cell.name.text=name.lastPathComponent;cell.detail.text=directory?T(@"Folder"):[NSByteCountFormatter stringFromByteCount:[item[@"bytes"] longLongValue] countStyle:NSByteCountFormatterCountStyleFile];
    cell.contentView.backgroundColor=selected?[Accent() colorWithAlphaComponent:.18]:Surface();cell.check.hidden=!selected;cell.check.tintColor=Accent();
    cell.accessibilityLabel=name;cell.accessibilityValue=[self itemDetail:item];cell.accessibilityTraits=selected?UIAccessibilityTraitSelected|UIAccessibilityTraitButton:UIAccessibilityTraitButton;
}

#pragma mark Interaction

- (void)collectionView:(UICollectionView *)view didSelectItemAtIndexPath:(NSIndexPath *)indexPath {
    if(view==self.otherCollection){[self otherSelected:indexPath];return;}
    [view deselectItemAtIndexPath:indexPath animated:YES];
    NSString *name=[self.filesSource itemIdentifierForIndexPath:indexPath];NSDictionary *item=self.entryByName[name];if(!item)return;
    if([item[@"unavailable"] boolValue]){[self unavailableLocation:name];return;}
    if(self.selection.count||self.selectionMode){[self toggleSelection:name];return;}
    if([item[@"directory"] boolValue]){[self openFolder:[self itemPath:item]];return;}
    [self openItem:item];
}
- (UIContextMenuConfiguration *)collectionView:(UICollectionView *)view contextMenuConfigurationForItemsAtIndexPaths:(NSArray<NSIndexPath *> *)paths point:(CGPoint)point {
    if(paths.count!=1||view!=self.filesCollection)return nil;NSDictionary *item=self.entryByName[[self.filesSource itemIdentifierForIndexPath:paths.firstObject]];if(!item)return nil;
    return [UIContextMenuConfiguration configurationWithIdentifier:nil previewProvider:nil actionProvider:^UIMenu *(NSArray *suggested){return [self menuForItem:item];}];
}
- (UISwipeActionsConfiguration *)trailingSwipe:(NSIndexPath *)indexPath {
    NSDictionary *item=self.entryByName[[self.filesSource itemIdentifierForIndexPath:indexPath]];
    if(item&&[self.path isEqual:@"/"]&&!self.peer.length&&[self locationNamed:item[@"name"]]){
        UIContextualAction *remove=[UIContextualAction contextualActionWithStyle:UIContextualActionStyleDestructive title:T(@"Remove") handler:^(UIContextualAction *action,UIView *source,void (^done)(BOOL)){[self removeLocation:item[@"name"]];done(NO);}];
        remove.image=[UIImage systemImageNamed:@"minus.circle"];return [UISwipeActionsConfiguration configurationWithActions:@[remove]];}
    if(!item||[self.path isEqual:@"/"]||self.selection.count||self.selectionMode)return nil;
    UIContextualAction *remove=[UIContextualAction contextualActionWithStyle:UIContextualActionStyleDestructive title:T(@"Delete") handler:^(UIContextualAction *action,UIView *source,void (^done)(BOOL)){
        [self.selection removeAllObjects];[self.selection addObject:item[@"name"]];[self deleteSelection];done(NO);}];
    remove.image=[UIImage systemImageNamed:@"trash"];
    UIContextualAction *rename=[UIContextualAction contextualActionWithStyle:UIContextualActionStyleNormal title:T(@"Rename") handler:^(UIContextualAction *action,UIView *source,void (^done)(BOOL)){[self editItem:item];done(YES);}];
    rename.image=[UIImage systemImageNamed:@"pencil"];rename.backgroundColor=UIColor.systemOrangeColor;
    UISwipeActionsConfiguration *config=[UISwipeActionsConfiguration configurationWithActions:@[remove,rename]];config.performsFirstActionWithFullSwipe=NO;return config;
}
- (UISwipeActionsConfiguration *)leadingSwipe:(NSIndexPath *)indexPath {
    NSDictionary *item=self.entryByName[[self.filesSource itemIdentifierForIndexPath:indexPath]];if(!item||self.selection.count||self.selectionMode)return nil;
    UIContextualAction *select=[UIContextualAction contextualActionWithStyle:UIContextualActionStyleNormal title:T(@"Select") handler:^(UIContextualAction *action,UIView *source,void (^done)(BOOL)){[self toggleSelection:item[@"name"]];done(YES);}];
    select.image=[UIImage systemImageNamed:@"checkmark.circle"];select.backgroundColor=UIColor.systemBlueColor;
    NSMutableArray *actions=[NSMutableArray arrayWithObject:select];
    if([self localPathFor:item]&&![item[@"directory"] boolValue]){UIContextualAction *share=[UIContextualAction contextualActionWithStyle:UIContextualActionStyleNormal title:T(@"Share") handler:^(UIContextualAction *action,UIView *source,void (^done)(BOOL)){[self shareItems:@[item] from:source];done(YES);}];
        share.image=[UIImage systemImageNamed:@"square.and.arrow.up"];share.backgroundColor=UIColor.systemTealColor;[actions addObject:share];}
    return [UISwipeActionsConfiguration configurationWithActions:actions];
}

// Everything that can be done with one item, as a native menu (context menu and the … button).
- (UIMenu *)menuForItem:(NSDictionary *)item {
    BOOL directory=[item[@"directory"] boolValue],root=[self.path isEqual:@"/"],local=!self.peer.length;NSString *name=item[@"name"];
    NSMutableArray *open=[NSMutableArray new];
    [open addObject:[UIAction actionWithTitle:T(@"Open") image:[UIImage systemImageNamed:directory?@"folder":@"eye"] identifier:nil handler:^(UIAction *a){if(directory)[self openFolder:[self itemPath:item]];else [self openItem:item];}]];
    if(local&&[self isText:item]&&self.filesBase.length)[open addObject:[UIAction actionWithTitle:T(@"Edit") image:[UIImage systemImageNamed:@"square.and.pencil"] identifier:nil handler:^(UIAction *a){[self editText:item];}]];
    if(local&&!directory&&!root)[open addObject:[UIAction actionWithTitle:T(@"Share") image:[UIImage systemImageNamed:@"square.and.arrow.up"] identifier:nil handler:^(UIAction *a){[self shareItems:@[item] from:nil];}]];
    NSMutableArray *edit=[NSMutableArray new];
    [edit addObject:[UIAction actionWithTitle:T(@"Select") image:[UIImage systemImageNamed:@"checkmark.circle"] identifier:nil handler:^(UIAction *a){[self toggleSelection:name];}]];
    if([self twoPanels]&&!root){[edit addObject:[UIAction actionWithTitle:T(@"Copy to target panel") image:[UIImage systemImageNamed:@"arrow.right.doc.on.clipboard"] identifier:nil handler:^(UIAction *a){[self copyToOther:NO names:@[name]];}]];
        if(local&&!self.otherPeer.length)[edit addObject:[UIAction actionWithTitle:T(@"Move to target panel") image:[UIImage systemImageNamed:@"arrow.right.square"] identifier:nil handler:^(UIAction *a){[self copyToOther:YES names:@[name]];}]];}
    [edit addObject:[UIAction actionWithTitle:T(@"Copy to…") image:[UIImage systemImageNamed:@"doc.on.doc"] identifier:nil handler:^(UIAction *a){[self.selection removeAllObjects];[self.selection addObject:name];[self chooseDestination:NO];}]];
    if(local&&!root)[edit addObject:[UIAction actionWithTitle:T(@"Move to…") image:[UIImage systemImageNamed:@"folder"] identifier:nil handler:^(UIAction *a){[self.selection removeAllObjects];[self.selection addObject:name];[self chooseDestination:YES];}]];
    if(local&&!root)[edit addObject:[UIAction actionWithTitle:T(@"Duplicate") image:[UIImage systemImageNamed:@"plus.square.on.square"] identifier:nil handler:^(UIAction *a){[self duplicateItem:item];}]];
    if(!root)[edit addObject:[UIAction actionWithTitle:T(@"Rename") image:[UIImage systemImageNamed:@"pencil"] identifier:nil handler:^(UIAction *a){[self editItem:item];}]];
    if(local&&!root&&[self isArchive:item])[edit addObject:[UIAction actionWithTitle:T(@"Extract here") image:[UIImage systemImageNamed:@"archivebox"] identifier:nil handler:^(UIAction *a){[self extractItem:item];}]];
    if(local&&!root)[edit addObject:[UIAction actionWithTitle:T(@"Compress") image:[UIImage systemImageNamed:@"archivebox.fill"] identifier:nil handler:^(UIAction *a){[self compressNames:@[name]];}]];
    if(directory&&!root){NSString *folderPath=[self itemPath:item];BOOL favorite=[self isFavorite:folderPath];
        [edit addObject:[UIAction actionWithTitle:T(favorite?@"Remove from favorites":@"Add to favorites") image:[UIImage systemImageNamed:favorite?@"star.slash":@"star"] identifier:nil handler:^(UIAction *a){[self toggleFavorite:folderPath name:name.lastPathComponent];}]];}
    NSMutableArray *info=[NSMutableArray arrayWithObject:[UIAction actionWithTitle:T(@"Properties") image:[UIImage systemImageNamed:@"info.circle"] identifier:nil handler:^(UIAction *a){[self showProperties:item];}]];
    NSMutableArray *sections=[NSMutableArray arrayWithObjects:[UIMenu menuWithTitle:@"" image:nil identifier:nil options:UIMenuOptionsDisplayInline children:open],[UIMenu menuWithTitle:@"" image:nil identifier:nil options:UIMenuOptionsDisplayInline children:edit],[UIMenu menuWithTitle:@"" image:nil identifier:nil options:UIMenuOptionsDisplayInline children:info],nil];
    if(root&&local&&[self locationNamed:name]){UIAction *forget=[UIAction actionWithTitle:T(@"Remove location · keep files") image:[UIImage systemImageNamed:@"minus.circle"] identifier:nil handler:^(UIAction *a){[self removeLocation:name];}];forget.attributes=UIMenuElementAttributesDestructive;
        [sections addObject:[UIMenu menuWithTitle:@"" image:nil identifier:nil options:UIMenuOptionsDisplayInline children:@[forget]]];}
    if(!root){UIAction *remove=[UIAction actionWithTitle:T(@"Delete") image:[UIImage systemImageNamed:@"trash"] identifier:nil handler:^(UIAction *a){[self.selection removeAllObjects];[self.selection addObject:name];[self deleteSelection];}];remove.attributes=UIMenuElementAttributesDestructive;
        [sections addObject:[UIMenu menuWithTitle:@"" image:nil identifier:nil options:UIMenuOptionsDisplayInline children:@[remove]]];}
    return [UIMenu menuWithTitle:name.lastPathComponent children:sections];
}
- (void)showProperties:(NSDictionary *)item {
    NSString *path=[self itemPath:item];NSString *size=[item[@"directory"] boolValue]?T(@"Folder size has not been calculated"):[NSByteCountFormatter stringFromByteCount:[item[@"bytes"] longLongValue] countStyle:NSByteCountFormatterCountStyleFile];
    NSString *date=[item[@"modified"] doubleValue]>0?[NSDateFormatter localizedStringFromDate:[NSDate dateWithTimeIntervalSince1970:[item[@"modified"] doubleValue]] dateStyle:NSDateFormatterMediumStyle timeStyle:NSDateFormatterShortStyle]:@"—";
    UIAlertController *alert=[UIAlertController alertControllerWithTitle:item[@"name"] message:[NSString stringWithFormat:@"%@\n\n%@: %@\n%@: %@",path,T(@"Size"),size,T(@"Modified"),date] preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleCancel handler:nil]];[self presentViewController:alert animated:YES completion:nil];
}
- (void)openItem:(NSDictionary *)item {
    [self previewItem:item];
}
- (void)shareItems:(NSArray *)items from:(UIView *)source {
    NSMutableArray *urls=[NSMutableArray new];for(NSDictionary *item in items){NSString *file=[self localPathFor:item];if(file)[urls addObject:[NSURL fileURLWithPath:file]];}
    if(!urls.count)return;
    UIActivityViewController *share=[[UIActivityViewController alloc]initWithActivityItems:urls applicationActivities:nil];
    share.popoverPresentationController.sourceView=source?:self.view;if(!source)share.popoverPresentationController.sourceRect=CGRectMake(CGRectGetMidX(self.view.bounds),CGRectGetMidY(self.view.bounds),1,1);
    [self presentViewController:share animated:YES completion:nil];
}

#pragma mark Locations

// A folder chosen in Files: its bookmark, whether it is on a network share, and whether it opens now.
- (NSDictionary *)locationNamed:(NSString *)name {
    for(NSDictionary *value in [NSUserDefaults.standardUserDefaults arrayForKey:@"folderBookmarks"])if([value[@"name"] isEqual:name]){
        NSURL *url=self.folderAccess[value[@"key"]];NSNumber *local=nil;if(url)[url getResourceValue:&local forKey:NSURLVolumeIsLocalKey error:nil];
        return @{@"key":value[@"key"],@"name":name,@"available":@(url!=nil),@"network":@(url&&local&&!local.boolValue)};}
    return nil;
}
- (NSArray *)unavailableLocations {
    NSMutableArray *items=[NSMutableArray new];
    for(NSDictionary *value in [NSUserDefaults.standardUserDefaults arrayForKey:@"folderBookmarks"])if(!self.folderAccess[value[@"key"]])[items addObject:@{@"name":value[@"name"]?:@"?",@"directory":@YES,@"unavailable":@YES}];
    return items;
}
- (void)removeLocation:(NSString *)name {
    NSDictionary *location=[self locationNamed:name];if(!location)return;
    UIAlertController *ask=[UIAlertController alertControllerWithTitle:[NSString stringWithFormat:T(@"Remove location „%@“? Files stay where they are."),name] message:nil preferredStyle:UIAlertControllerStyleActionSheet];
    ask.popoverPresentationController.sourceView=self.view;ask.popoverPresentationController.sourceRect=CGRectMake(CGRectGetMidX(self.view.bounds),CGRectGetMidY(self.view.bounds),1,1);ask.popoverPresentationController.permittedArrowDirections=0;
    [ask addAction:[UIAlertAction actionWithTitle:T(@"Remove location · keep files") style:UIAlertActionStyleDestructive handler:^(UIAlertAction *action){
        NSMutableArray *items=[NSMutableArray new];for(NSDictionary *item in [NSUserDefaults.standardUserDefaults arrayForKey:@"folderBookmarks"])if(![item[@"key"] isEqual:location[@"key"]])[items addObject:item];
        [NSUserDefaults.standardUserDefaults setObject:items forKey:@"folderBookmarks"];NSURL *url=self.folderAccess[location[@"key"]];[self.folderAccess removeObjectForKey:location[@"key"]];
        [self configureFolders:^{[url stopAccessingSecurityScopedResource];if([self.screen isEqual:@"files"])[self openFolder:@"/"];else [self showHome];[self toast:T(@"Location removed")];}];}]];
    [ask addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];
    [self presentViewController:ask animated:YES completion:nil];
}
- (void)unavailableLocation:(NSString *)name {
    UIAlertController *alert=[UIAlertController alertControllerWithTitle:name message:T(@"This location is not available now. Network folders open only on the network they belong to; choose the folder in Files again if it moved.") preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Choose again in Files…") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a){[self addFolder];}]];
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Remove location · keep files") style:UIAlertActionStyleDestructive handler:^(UIAlertAction *a){[self removeLocation:name];}]];
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];[self presentViewController:alert animated:YES completion:nil];
}

#pragma mark Folders, search, archives, favorites

- (NSString *)itemCount:(NSUInteger)count {
    // Czech needs three forms: 1 položka, 2–4 položky, 5+ položek.
    NSString *form=count==1?@"item":(count>=2&&count<=4)?@"items (2-4)":@"items";
    NSString *word=T(form);if([word isEqual:@"items (2-4)"])word=@"items";
    return [NSString stringWithFormat:@"%lu %@",(unsigned long)count,word];
}
- (void)openFolder:(NSString *)path {
    self.path=path;self.filter=@"";self.searchQuery=nil;[self.selection removeAllObjects];[self showFiles];
}
- (void)askSearch {
    UIAlertController *form=[UIAlertController alertControllerWithTitle:T(@"Search subfolders…") message:self.path preferredStyle:UIAlertControllerStyleAlert];
    [form addTextFieldWithConfigurationHandler:^(UITextField *field){field.placeholder=T(@"Part of a file name");field.autocorrectionType=UITextAutocorrectionTypeNo;field.returnKeyType=UIReturnKeySearch;}];
    [form addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];
    UIAlertAction *go=[UIAlertAction actionWithTitle:T(@"Search") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a){NSString *text=form.textFields.firstObject.text;if(text.length)[self deepSearch:text];}];
    [form addAction:go];form.preferredAction=go;[self presentViewController:form animated:YES completion:nil];
}
- (void)deepSearch:(NSString *)query {
    NSString *path=self.path;self.searchQuery=query;self.filter=@"";self.fileEntries=@[];[self.selection removeAllObjects];self.selectionMode=NO;[self showFilesLoading];
    [self call:@"search_local" args:@[path,query] then:^(NSString *json){if(![self.path isEqual:path]||![self.searchQuery isEqual:query])return;
        NSDictionary *value=[NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];
        self.fileEntries=[value[@"results"] isKindOfClass:NSArray.class]?value[@"results"]:@[];self.searchComplete=[value[@"complete"] boolValue];[self renderFiles];}];
}
- (BOOL)isArchive:(NSDictionary *)item {
    if([item[@"directory"] boolValue])return NO;NSString *name=[item[@"name"] lowercaseString];
    for(NSString *suffix in @[@".zip",@".tar",@".tgz",@".tar.gz",@".tar.bz2",@".tar.xz"])if([name hasSuffix:suffix])return YES;return NO;
}
// Long local operations share one progress alert with Stop, then refresh the folder.
- (void)runOperation:(NSString *)title call:(NSString *)name args:(NSArray *)args done:(void (^)(NSDictionary *))done {
    [self startOperation:title route:self.path.lastPathComponent call:name args:args done:done];return;
    self.operationAlert=[UIAlertController alertControllerWithTitle:title message:T(@"Preparing files…") preferredStyle:UIAlertControllerStyleAlert];
    [self.operationAlert addAction:[UIAlertAction actionWithTitle:T(@"Stop") style:UIAlertActionStyleDestructive handler:^(UIAlertAction *action){dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{CoreCall(@"cancel_operation",@[],NO);});}]];
    [self presentViewController:self.operationAlert animated:YES completion:^{[self call:name args:args then:^(NSString *json){UIAlertController *busy=self.operationAlert;self.operationAlert=nil;
        NSDictionary *value=[NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];
        [busy dismissViewControllerAnimated:YES completion:^{[self.selection removeAllObjects];self.selectionMode=NO;[self showFiles];if(done)done([value isKindOfClass:NSDictionary.class]?value:@{});}];}];}];
}
- (void)extractItem:(NSDictionary *)item {
    [self runOperation:T(@"Extract here") call:@"extract_archive" args:@[[self itemPath:item]] done:^(NSDictionary *value){[self toast:[NSString stringWithFormat:@"%@\n%@",T(@"Extracted to"),value[@"folder"]?:@""]];}];
}
- (void)compressNames:(NSArray *)names {
    if(!names.count)return;NSMutableArray *paths=[NSMutableArray new];for(NSString *name in names)[paths addObject:[self.path stringByAppendingPathComponent:name]];
    NSString *suggested=names.count==1?[names.firstObject lastPathComponent].stringByDeletingPathExtension:T(@"Archive");
    UIAlertController *form=[UIAlertController alertControllerWithTitle:T(@"Compress") message:[NSString stringWithFormat:@"%lu → ZIP",(unsigned long)names.count] preferredStyle:UIAlertControllerStyleAlert];
    [form addTextFieldWithConfigurationHandler:^(UITextField *field){field.text=suggested;field.autocorrectionType=UITextAutocorrectionTypeNo;field.clearButtonMode=UITextFieldViewModeWhileEditing;}];
    [form addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];
    UIAlertAction *go=[UIAlertAction actionWithTitle:T(@"Compress") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a){
        NSString *json=[[NSString alloc]initWithData:[NSJSONSerialization dataWithJSONObject:paths options:0 error:nil] encoding:NSUTF8StringEncoding];
        [self runOperation:T(@"Compress") call:@"compress_items" args:@[json,form.textFields.firstObject.text.length?form.textFields.firstObject.text:suggested] done:^(NSDictionary *value){[self toast:[NSString stringWithFormat:@"%@\n%@",T(@"Created"),value[@"file"]?:@""]];}];}];
    [form addAction:go];form.preferredAction=go;[self presentViewController:form animated:YES completion:nil];
}
// Favorites and recent places are kept on this iPhone only.
- (NSArray *)places:(NSString *)key { NSArray *value=[NSUserDefaults.standardUserDefaults arrayForKey:key];return [value isKindOfClass:NSArray.class]?value:@[]; }
- (BOOL)isFavorite:(NSString *)path { for(NSDictionary *place in [self places:@"favorites"])if([place[@"path"] isEqual:path]&&[place[@"peer"] isEqual:self.peer])return YES;return NO; }
- (void)toggleFavorite:(NSString *)path name:(NSString *)name {
    NSMutableArray *places=[[self places:@"favorites"] mutableCopy];BOOL removed=NO;
    for(NSDictionary *place in [places copy])if([place[@"path"] isEqual:path]&&[place[@"peer"] isEqual:self.peer]){[places removeObject:place];removed=YES;}
    if(!removed)[places addObject:@{@"peer":self.peer?:@"",@"path":path,@"name":name?:path.lastPathComponent}];
    [NSUserDefaults.standardUserDefaults setObject:places forKey:@"favorites"];
    [self toast:T(removed?@"Removed from favorites":@"Added to favorites")];
}
- (void)rememberPlace:(NSString *)key path:(NSString *)path name:(NSString *)name {
    if(!path.length||[path isEqual:@"/"])return;
    NSMutableArray *places=[[self places:key] mutableCopy];
    for(NSDictionary *place in [places copy])if([place[@"path"] isEqual:path]&&[place[@"peer"] isEqual:self.peer])[places removeObject:place];
    [places insertObject:@{@"peer":self.peer?:@"",@"path":path,@"name":name?:path.lastPathComponent} atIndex:0];
    while(places.count>10)[places removeLastObject];
    [NSUserDefaults.standardUserDefaults setObject:places forKey:key];
}

#pragma mark Selection

- (void)startSelection {
    // Selection mode starts with nothing chosen; a placeholder keeps the mode on until the first tap.
    if(!self.selection.count&&self.entryByName.count){self.selectionMode=YES;[self reloadVisibleFiles];[self updateSelectionUI];}
}
- (void)toggleSelection:(NSString *)name {
    if([self.selection containsObject:name])[self.selection removeObject:name];else [self.selection addObject:name];
    self.selectionMode=YES;
    [self reloadVisibleFiles];[self updateSelectionUI];
}
- (void)endSelection { [self.selection removeAllObjects];self.selectionMode=NO;[self reloadVisibleFiles];[self updateSelectionUI]; }
- (void)reloadVisibleFiles {
    NSDiffableDataSourceSnapshot *snapshot=self.filesSource.snapshot;if(!snapshot.numberOfItems)return;
    [snapshot reconfigureItemsWithIdentifiers:snapshot.itemIdentifiers];[self.filesSource applySnapshot:snapshot animatingDifferences:NO];
}
- (UIButton *)barButton:(NSString *)title symbol:(NSString *)symbol color:(UIColor *)color enabled:(BOOL)enabled action:(dispatch_block_t)action {
    UIButton *button=[UIButton buttonWithType:UIButtonTypeSystem];UIButtonConfiguration *cfg=[UIButtonConfiguration plainButtonConfiguration];
    cfg.title=title;cfg.image=[UIImage systemImageNamed:symbol];cfg.imagePlacement=NSDirectionalRectEdgeTop;cfg.imagePadding=5;cfg.baseForegroundColor=color;cfg.contentInsets=NSDirectionalEdgeInsetsMake(8,2,8,2);
    cfg.titleTextAttributesTransformer=^NSDictionary *(NSDictionary *attributes){NSMutableDictionary *result=[attributes mutableCopy];result[NSFontAttributeName]=[UIFont systemFontOfSize:11 weight:UIFontWeightMedium];return result;};
    button.configuration=cfg;button.enabled=enabled;[button addAction:[UIAction actionWithHandler:^(UIAction *a){action();}] forControlEvents:UIControlEventPrimaryActionTriggered];return button;
}
- (void)updateSelectionUI {
    BOOL active=[self.screen isEqual:@"files"]&&(self.selection.count||self.selectionMode);
    self.selectionBar.hidden=!active;self.tabs.hidden=active;
    for(UIView *view in self.selectionBar.arrangedSubviews){[self.selectionBar removeArrangedSubview:view];[view removeFromSuperview];}
    [self updateFileCount];
    if(!active)return;
    BOOL some=self.selection.count>0,local=!self.peer.length,root=[self.path isEqual:@"/"];
    NSMutableArray *items=[NSMutableArray new];for(NSString *name in self.selection){NSDictionary *item=self.entryByName[name];if(item&&![item[@"directory"] boolValue])[items addObject:item];}
    BOOL all=self.selection.count==self.entryByName.count;
    [self.selectionBar addArrangedSubview:[self barButton:T(all?@"Deselect all":@"Select all") symbol:all?@"circle.dashed":@"checkmark.circle.fill" color:Accent() enabled:YES action:^{if(all){[self.selection removeAllObjects];}else [self.selection addObjectsFromArray:self.entryByName.allKeys];self.selectionMode=YES;[self reloadVisibleFiles];[self updateSelectionUI];}]];
    BOOL two=[self twoPanels];
    [self.selectionBar addArrangedSubview:[self barButton:T(two?@"Copy →":@"Copy") symbol:@"doc.on.doc" color:Accent() enabled:some action:^{if(two)[self copyToOther:NO names:self.selection.allObjects];else [self chooseDestination:NO];}]];
    if(local&&!root)[self.selectionBar addArrangedSubview:[self barButton:T(two?@"Move →":@"Move") symbol:@"folder" color:Accent() enabled:some action:^{if(two)[self copyToOther:YES names:self.selection.allObjects];else [self chooseDestination:YES];}]];
    if(local&&!root&&!self.searchQuery)[self.selectionBar addArrangedSubview:[self barButton:T(@"Compress") symbol:@"archivebox" color:Accent() enabled:some action:^{[self compressNames:self.selection.allObjects];}]];
    if(local&&!root)[self.selectionBar addArrangedSubview:[self barButton:T(@"Share") symbol:@"square.and.arrow.up" color:Accent() enabled:items.count>0 action:^{[self shareItems:items from:nil];}]];
    if(!root)[self.selectionBar addArrangedSubview:[self barButton:T(@"Delete") symbol:@"trash" color:UIColor.systemRedColor enabled:some action:^{[self deleteSelection];}]];
    [self.selectionBar addArrangedSubview:[self barButton:T(@"Done") symbol:@"xmark.circle" color:UIColor.secondaryLabelColor enabled:YES action:^{[self endSelection];}]];
}
#endif
